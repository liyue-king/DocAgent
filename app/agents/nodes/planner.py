"""
====================================================================
文件用途：planner —— 排版规划节点（确定性快路径 + LLM 增量路径）
====================================================================
作用：
    生成原子操作队列 task_queue。双路径设计（蓝图 6.2）：
    - 确定性快路径：纯模板匹配，按模板 config 对 DOM 段落分组生成指令，
      0 token、<1s、planner_mode="deterministic"；
    - LLM 增量路径：检测到用户个性化需求（或 EntryGuard 强制切换）时，
      在确定性队列基础上调用 LLM 生成少量"增量/覆盖"指令（~200 tokens），
      temperature=0，失败自动回退确定性结果；
    - 重试增量修补：Validator 返回 missed 后，仅针对未达标段落、未达标
      维度生成修补指令（非全量重规划），planner_llm_calls 不再增加。
依赖：
    - app.services.llm.chat_json（DeepSeek 客户端，延迟调用）
    - app.agents.nodes._common（notify）
====================================================================
"""

from __future__ import annotations

import json  # 序列化提示词
import logging  # 标准库日志
from typing import Any  # 泛型类型

from app.agents.nodes._common import is_cancelled, notify  # 取消判定 / 日志持久化
from app.models import LogLevel, TaskStatus  # 枚举

logger = logging.getLogger(__name__)  # 模块级日志器
NODE_NAME = "planner"  # 节点名

# action 白名单（与 entry_guard 保持一致，防止 LLM 输出越权指令）
ACTION_WHITELIST = {
    "set_font",
    "set_font_size",
    "set_bold",
    "set_italic",
    "set_line_spacing",
    "set_paragraph_space",
}

# 个性化需求关键词：命中任意一个即认为用户要求覆盖模板默认样式 → LLM 增量路径
_PERSONALIZATION_KEYWORDS = (
    "不要加粗",
    "不要粗",
    "改成",
    "改为",
    "换成",
    "调成",
    "调整",
    "修改",
    "设置",
    "字号",
    "字体",
    "楷体",
    "仿宋",
    "黑体",
    "宋体",
    "加粗",
    "斜体",
    "行距",
    "间距",
    "缩进",
    "小四",
    "四号",
    "五号",
    "三号",
    "小二",
    "二号",
)


def _op_set_font(pid: int, cfg: dict[str, Any]) -> dict[str, Any]:
    return {"action": "set_font", "para_ids": [pid], "font": cfg["font_name"]}


def _op_set_font_size(pid: int, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "set_font_size",
        "para_ids": [pid],
        "size_pt": cfg["font_size_pt"],
    }


def _op_set_bold(pid: int, cfg: dict[str, Any]) -> dict[str, Any]:
    return {"action": "set_bold", "para_ids": [pid], "bold": cfg.get("bold", False)}


def _op_set_line_spacing(pid: int, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "set_line_spacing",
        "para_ids": [pid],
        "rule": cfg.get("line_spacing_rule", "MULTIPLE"),
        "value": cfg.get("line_spacing_value"),
    }


def _op_set_paragraph_space(pid: int, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "set_paragraph_space",
        "para_ids": [pid],
        "space_before_pt": cfg.get("space_before_pt", 0),
        "space_after_pt": cfg.get("space_after_pt", 0),
    }


# 校验维度 → 指令构造器映射（重试增量修补用）
_DIM_OP_BUILDERS: dict[str, Any] = {
    "font": _op_set_font,
    "font_size": _op_set_font_size,
    "bold": _op_set_bold,
    "line_spacing": _op_set_line_spacing,
    "paragraph_space": _op_set_paragraph_space,
}


def _needs_llm(prompt: str) -> bool:
    """判断用户提示词是否含个性化需求（命中关键词即走 LLM 增量路径）。"""
    if not prompt:
        return False
    return any(kw in prompt for kw in _PERSONALIZATION_KEYWORDS)


def build_style_ops(
    template_config: dict[str, Any], doc_dom_serial: dict[str, Any]
) -> list[dict[str, Any]]:
    """确定性快路径：按模板 config 对 DOM 段落按样式分组生成原子指令。

    含图片/形状/公式的段落（has_image）豁免行距/段距维度：EXACTLY 固定行距
    会裁切高于行高的图片/公式（Word 渲染行为），且 validator 已同步豁免
    该维度的校验，两端口径一致避免重试闭环。

    :param template_config: 模板 config（含 paragraph_styles）
    :param doc_dom_serial: 可序列化 DOM（段落 id/style）
    :return: 原子指令队列
    """
    styles = template_config.get("paragraph_styles", {})
    paragraphs = doc_dom_serial.get("paragraphs", [])
    by_id = {p.get("id"): p for p in paragraphs}
    # 按样式分组段落 id
    style_group: dict[str, list[int]] = {}
    for p in paragraphs:
        s = p.get("style", "other")
        # 正文样式但原本带加粗的段落（封面字段/强调）→ 保留原格式，模板不覆盖
        if s == "normal" and p.get("keep_format"):
            continue
        # 纯图片/公式段（无文本）→ 无可排版内容，整段排除（与 validator 口径一致）
        if p.get("has_image") and not p.get("text"):
            continue
        if s in ("heading_1", "heading_2", "heading_3", "normal"):
            style_group.setdefault(s, []).append(p["id"])

    ops: list[dict[str, Any]] = []
    for style_key, para_ids in style_group.items():
        cfg = styles.get(style_key)
        if not cfg:
            continue  # 模板未定义该样式，跳过
        # 含图/公式段落：行距/段距指令不覆盖（裁切风险，validator 同步豁免）
        spacing_ids = [
            pid for pid in para_ids if not by_id.get(pid, {}).get("has_image")
        ]
        # 五个维度整组指令（para_ids 为整组）
        ops.append(
            {"action": "set_font", "para_ids": para_ids, "font": cfg["font_name"]}
        )
        ops.append(
            {
                "action": "set_font_size",
                "para_ids": para_ids,
                "size_pt": cfg["font_size_pt"],
            }
        )
        ops.append(
            {"action": "set_bold", "para_ids": para_ids, "bold": cfg.get("bold", False)}
        )
        if spacing_ids:  # 非空才生成行距/段距指令
            ops.append(
                {
                    "action": "set_line_spacing",
                    "para_ids": spacing_ids,
                    "rule": cfg.get("line_spacing_rule", "MULTIPLE"),
                    "value": cfg.get("line_spacing_value"),
                }
            )
            ops.append(
                {
                    "action": "set_paragraph_space",
                    "para_ids": spacing_ids,
                    "space_before_pt": cfg.get("space_before_pt", 0),
                    "space_after_pt": cfg.get("space_after_pt", 0),
                }
            )
    return ops


def build_missed_patch_ops(
    template_config: dict[str, Any],
    validation_report: dict[str, Any],
    doc_dom_serial: dict[str, Any] | None = None,
    llm_overrides: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """重试增量修补：仅针对 missed 段落的未达标维度生成指令。

    含图片/形状/公式的段落（has_image）豁免行距/段距维度，与 build_style_ops
    及 validator 的豁免口径保持一致（防止修补指令重新引入裁切风险）。
    **用户个性化覆盖（llm_overrides）优先于模板值**：被 LLM 覆盖的
    (para_id, dim) 按用户目标值修补，不再被"修回模板"（v6.2）。

    :param template_config: 模板 config
    :param validation_report: Validator 输出（missed 含 para_id/style/reason）
    :param doc_dom_serial: 可序列化 DOM（段落 has_image 判定用，可空）
    :param llm_overrides: {para_id: {dim: 用户目标值}}（planner 首轮写入）
    :return: 增量修补指令队列（空列表表示无遗漏）
    """
    styles = template_config.get("paragraph_styles", {})
    overrides = llm_overrides or {}
    image_ids = {
        p.get("id")
        for p in (doc_dom_serial or {}).get("paragraphs", [])
        if p.get("has_image")
    }
    ops: list[dict[str, Any]] = []
    for miss in validation_report.get("missed", []):
        para_id = miss.get("para_id")
        style = miss.get("style")
        cfg = styles.get(style)
        if para_id is None or not cfg:
            continue  # 样式未定义或无段号，跳过
        # reason 形如 "font,line_spacing"，逐维度生成对应修补指令
        dims = [
            d.strip() for d in (miss.get("reason") or "font").split(",") if d.strip()
        ]
        if para_id in image_ids:  # 含图/公式段落：不修补行距/段距
            dims = [d for d in dims if d not in ("line_spacing", "paragraph_space")]
        para_overrides = overrides.get(para_id) or {}
        for dim in dims:
            if dim in para_overrides:
                # 用户个性化覆盖：按用户目标值修补（不再回退模板值）
                ops.append(_override_patch_op(para_id, dim, para_overrides))
                continue
            builder = _DIM_OP_BUILDERS.get(dim)
            if builder:
                ops.append(builder(para_id, cfg))
    return ops


def _override_patch_op(
    para_id: int, dim: str, target: dict[str, Any]
) -> dict[str, Any]:
    """按用户目标值生成修补指令（llm_overrides 场景）。"""
    if dim == "font":
        return {"action": "set_font", "para_ids": [para_id], "font": target["font"]}
    if dim == "font_size":
        return {
            "action": "set_font_size",
            "para_ids": [para_id],
            "size_pt": target["font_size"],
        }
    if dim == "bold":
        return {"action": "set_bold", "para_ids": [para_id], "bold": target["bold"]}
    if dim == "italic":
        return {"action": "set_italic", "para_ids": [para_id], "italic": target["italic"]}
    if dim == "line_spacing":
        return {
            "action": "set_line_spacing",
            "para_ids": [para_id],
            "rule": target["line_spacing_rule"],
            "value": target.get("line_spacing_value"),
        }
    if dim == "paragraph_space":
        return {
            "action": "set_paragraph_space",
            "para_ids": [para_id],
            "space_before_pt": target["space_before_pt"],
            "space_after_pt": target["space_after_pt"],
        }
    return {"action": dim, "para_ids": [para_id]}


# 各 action 字段值合法性校验（LLM 输出不可信：值非法时丢弃并记录 unmet）
_VALID_SPACING_RULES = {"SINGLE", "DOUBLE", "MULTIPLE", "EXACTLY", "AT_LEAST"}


def _validate_llm_op(
    op: dict[str, Any],
    max_para_id: int,
    image_ids: set[int],
) -> tuple[bool, str]:
    """校验单条 LLM 指令的值合法性（entry_guard 只查字段存在，这里查值）。

    :param op: LLM 输出的原子指令
    :param max_para_id: 允许的最大段落 id（summary 可见范围上限）
    :param image_ids: 含图片/公式段落 id（行距/段距有裁切风险，禁止）
    :return: (是否合法, 丢弃原因)
    """
    action = op.get("action")
    # para_ids 逐项检查
    for pid in op.get("para_ids", []):
        if not isinstance(pid, int) or isinstance(pid, bool):
            return False, f"para_id 非整数: {pid}"
        if pid < 0 or pid > max_para_id:
            return False, f"para_id 超出 LLM 可见范围: {pid}"
        if action in ("set_line_spacing", "set_paragraph_space") and pid in image_ids:
            return False, f"段落 {pid} 含图片/公式，行距/段距有裁切风险"
    # 按 action 校验字段值
    if action == "set_font":
        font = op.get("font")
        if not isinstance(font, str) or not font.strip():
            return False, "font 为空或非字符串"
        if len(font) > 50:
            return False, f"font 过长: {font[:20]}"
    elif action == "set_font_size":
        size = op.get("size_pt")
        if not isinstance(size, (int, float)) or isinstance(size, bool):
            return False, "size_pt 非数字"
        if not (6 <= float(size) <= 72):
            return False, f"size_pt 超出合理范围: {size}"
    elif action in ("set_bold", "set_italic"):
        flag = op.get("bold" if action == "set_bold" else "italic")
        if not isinstance(flag, bool):
            # 关键：字符串 "false" 是 truthy，直接写入会把加粗设成 true（语义反转）
            return False, f"{action} 值必须是布尔: {flag!r}"
    elif action == "set_line_spacing":
        rule = (op.get("rule") or "").upper()
        if rule not in _VALID_SPACING_RULES:
            return False, f"line_spacing 规则非法: {op.get('rule')!r}"
        value = op.get("value")
        if value is not None:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, "line_spacing 值非数字"
            if rule in ("MULTIPLE", "SINGLE", "DOUBLE") and not (1.0 <= float(value) <= 3.0):
                return False, f"倍数行距超出范围: {value}"
            if rule in ("EXACTLY", "AT_LEAST") and not (6 <= float(value) <= 100):
                return False, f"固定行距超出范围: {value}"
    elif action == "set_paragraph_space":
        for key in ("space_before_pt", "space_after_pt"):
            v = op.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return False, f"{key} 非数字"
            if not (0 <= float(v) <= 100):
                return False, f"{key} 超出范围: {v}"
    return True, ""


def _llm_augment(
    template_config: dict[str, Any],
    doc_dom_serial: dict[str, Any],
    prompt: str,
    base_queue: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, dict[int, dict[str, Any]], list[dict[str, Any]], bool]:
    """LLM 增量路径：在基础队列上生成增量/覆盖指令，并产出目标状态声明。

    :param template_config: 模板 config
    :param doc_dom_serial: 文档段落摘要
    :param prompt: 用户需求
    :param base_queue: 确定性基础队列
    :return: (extra_ops, tokens, llm_overrides, unmet_requirements, llm_degraded)
        - extra_ops: 白名单 + 值校验通过的增量指令
        - llm_overrides: {para_id: {dim: 用户目标值}}（validator 验收基准）
        - unmet_requirements: 被丢弃指令的明细（前端提示"哪些要求没实现"）
        - llm_degraded: True=LLM 不可用/未生效（个性化需求按模板处理）
    """
    paragraphs = doc_dom_serial.get("paragraphs", [])
    summary = [
        {"id": p["id"], "style": p.get("style"), "text": (p.get("text") or "")[:30]}
        for p in paragraphs[:200]
    ]
    max_visible_id = max((p["id"] for p in summary), default=-1)
    image_ids = {p["id"] for p in paragraphs if p.get("has_image")}

    system_prompt = (
        "你是文档排版规划助手。根据模板配置、文档段落结构与用户需求，"
        "输出额外或覆盖的原子排版指令。要求：仅输出 JSON 数组，"
        '每个元素形如 {"action":"set_font","para_ids":[0],"font":"楷体"}。'
        "action 必须是 set_font/set_font_size/set_bold/set_italic/"
        "set_line_spacing/set_paragraph_space 之一。"
        "para_ids 只能引用下方段落摘要中出现的 id；"
        "bold/italic 必须是 true/false 布尔值；"
        "line_spacing 的 rule 只能是 SINGLE/DOUBLE/MULTIPLE/EXACTLY/AT_LEAST；"
        "set_paragraph_space 需含 space_before_pt 与 space_after_pt。"
        "若无额外需求输出 []。"
    )
    user_prompt = (
        f"模板配置：{json.dumps(template_config, ensure_ascii=False)}\n"
        f"文档段落摘要：{json.dumps(summary, ensure_ascii=False)}\n"
        f"用户需求：{prompt}\n"
        f"已有指令队列：{json.dumps(base_queue, ensure_ascii=False)}\n"
        "请针对用户个性化需求，输出增量/覆盖指令 JSON 数组。"
    )
    try:
        from app.services.llm import chat_json  # 延迟导入（Key 未配置时抛异常）

        resp = chat_json(system_prompt, user_prompt, temperature=0.0, max_retries=1)
        data = resp["data"]
        tokens = int(resp.get("total_tokens", 0))
    except Exception as exc:  # LLM 不可用 / 解析失败 → 回退确定性队列
        logger.warning("[planner] LLM 增量路径失败，回退确定性队列: %s", exc)
        return [], 0, {}, [], True  # degraded=True：个性化需求未生效

    if not isinstance(data, list):  # LLM 未按约定输出数组
        logger.warning("[planner] LLM 输出非数组，丢弃: %r", str(data)[:200])
        return [], tokens, {}, [], True

    # 白名单 + 必填字段 + 值合法性过滤（entry_guard 二次兜底）
    extra: list[dict[str, Any]] = []
    overrides: dict[int, dict[str, Any]] = {}
    unmet: list[dict[str, Any]] = []
    for op in data:
        if not isinstance(op, dict):
            unmet.append({"action": "?", "reason": "指令非字典对象"})
            continue
        action = op.get("action")
        if action not in ACTION_WHITELIST:
            unmet.append({"action": str(action), "reason": "action 不在支持范围内"})
            continue
        if not isinstance(op.get("para_ids"), list) or not op["para_ids"]:
            unmet.append({"action": action, "reason": "para_ids 为空或非列表"})
            continue
        ok, reason = _validate_llm_op(op, max_visible_id, image_ids)
        if not ok:
            unmet.append({"action": action, "reason": reason, "detail": str(op)[:200]})
            continue
        extra.append(op)
        # 目标状态声明：同段同维后者覆盖（与 executor 执行顺序一致）
        for pid in op["para_ids"]:
            overrides.setdefault(pid, {})
            overrides[pid].update(_op_to_target(op))
    return extra, tokens, overrides, unmet, False


def _op_to_target(op: dict[str, Any]) -> dict[str, Any]:
    """把一条原子指令转成"目标状态声明"（validator 验收基准用）。

    注意：复合维度（line_spacing / paragraph_space）除子键外必须保留
    **dim 键本身**（如 "line_spacing"），供修补判定 `dim in overrides` 使用。
    """
    action = op["action"]
    if action == "set_font":
        return {"font": op["font"]}
    if action == "set_font_size":
        return {"font_size": float(op["size_pt"])}
    if action == "set_bold":
        return {"bold": op["bold"]}
    if action == "set_italic":
        return {"italic": op["italic"]}
    if action == "set_line_spacing":
        rule = (op["rule"] or "").upper()
        target: dict[str, Any] = {
            "line_spacing": rule,  # dim 键：修补判定用
            "line_spacing_rule": rule,  # 验收基准用
        }
        if op.get("value") is not None:
            target["line_spacing_value"] = float(op["value"])
        return target
    if action == "set_paragraph_space":
        return {
            "paragraph_space": True,  # dim 键：修补判定用
            "space_before_pt": float(op.get("space_before_pt", 0)),
            "space_after_pt": float(op.get("space_after_pt", 0)),
        }
    return {}


def planner_node(state: dict[str, Any]) -> dict[str, Any]:
    """规划节点：双路径生成 task_queue（含重试增量修补）。

    :param state: 当前状态（含模板配置 / doc_dom_serial / 用户需求 / 校验报告）
    :return: 状态更新（task_queue / planner_mode / token 统计 / agent_logs / status）
    """
    # 取消检查：LLM 增量路径耗时较长，取消后提前退出（error_node 收尾）
    if is_cancelled(state.get("task_id", "")):
        return {"status": "cancelled", "error_message": "任务已取消"}

    # ---- 兜底直通守卫：entry_guard 已保留原格式 → 不再重新规划（防御）----
    # 正常流程下 validator 对 fallback 短路直通 success，此处仅防路由异常回跳
    if state.get("entry_guard_fallback"):
        return {"status": "planning", "task_queue": []}

    template_config = state.get("selected_template_config") or {}
    doc_dom_serial = state.get("doc_dom_serial") or {"paragraphs": []}
    user_prompt = state.get("user_prompt", "")
    validation_report = state.get("validation_report") or {}
    retry_count = state.get("retry_count", 0)
    planner_mode = state.get("planner_mode", "deterministic")

    updates: dict[str, Any] = {}
    extra_ops: list[dict[str, Any]] = []
    used_tokens = 0
    llm_calls = state.get("planner_llm_calls", 0)
    mode = planner_mode  # 兜底初始值：重试修补轮不改变路径标识（修复未定义变量隐患）

    # ---- 分支 1：重试增量修补（仅针对 missed 段落）----
    if retry_count > 0 and validation_report.get("missed"):
        task_queue = build_missed_patch_ops(
            template_config,
            validation_report,
            doc_dom_serial,
            state.get("llm_overrides"),
        )
        logs = notify(
            state,
            f"校验未通过，重试第 {retry_count} 次：仅对 {len(validation_report.get('missed', []))} "
            f"个未达标段落增量修补，生成 {len(task_queue)} 条指令",
            NODE_NAME,
            level=LogLevel.WARNING,
            status=TaskStatus.PLANNING,
            progress=45,
            step=f"增量修补(第{retry_count}次)",
        )
    # ---- 分支 2：首轮规划（确定性 / LLM 增量）----
    else:
        degraded = False  # LLM 降级标记（确定性路径恒 False）
        unmet: list[dict[str, Any]] = []  # 未实现需求明细（确定性路径恒空）
        base_queue = build_style_ops(template_config, doc_dom_serial)  # 确定性快路径
        # 个性化需求 或 EntryGuard 强制切换 → LLM 增量
        if _needs_llm(user_prompt) or planner_mode == "llm_augmented":
            (
                extra_ops,
                used_tokens,
                overrides,
                unmet,
                degraded,
            ) = _llm_augment(
                template_config, doc_dom_serial, user_prompt, base_queue
            )
            llm_calls = llm_calls + 1  # 计入本次 LLM 调用（含失败尝试）
            mode = "llm_augmented"
            # 用户目标声明（validator 验收基准）与未实现需求明细写入 state
            merged_overrides = dict(state.get("llm_overrides") or {})
            for pid, dims in overrides.items():
                merged_overrides.setdefault(pid, {}).update(dims)
            updates["llm_overrides"] = merged_overrides
            updates["unmet_requirements"] = list(
                state.get("unmet_requirements") or []
            ) + unmet
            updates["llm_degraded"] = degraded or bool(
                state.get("llm_degraded")
            )
            log_msg = (
                f"规划完成（LLM 增量路径）：基础 {len(base_queue)} 条 + 个性化增量 {len(extra_ops)} 条，"
                f"共 {len(base_queue) + len(extra_ops)} 条原子指令"
            )
            if degraded:
                log_msg += "（LLM 不可用，个性化需求未生效，按模板处理）"
            elif unmet:
                log_msg += f"（{len(unmet)} 条个性化需求未实现：{unmet[0]['reason']}…）"
        else:
            mode = "deterministic"
            log_msg = (
                f"规划完成（确定性快路径）：生成 {len(base_queue)} 条原子指令，0 token"
            )
        task_queue = base_queue + extra_ops  # 合并
        logs = notify(
            state,
            log_msg,
            NODE_NAME,
            level=LogLevel.INFO if not (degraded or unmet) else LogLevel.WARNING,
            status=TaskStatus.PLANNING,
            progress=45,
            step="生成排版指令队列",
        )

    updates["task_queue"] = task_queue
    updates["planner_mode"] = (
        mode if retry_count == 0 else planner_mode
    )  # 修补轮不改变路径标识
    updates["planner_llm_calls"] = llm_calls
    updates["llm_total_tokens"] = state.get("llm_total_tokens", 0) + used_tokens
    updates["agent_logs"] = logs
    updates["status"] = "planning"
    return updates
