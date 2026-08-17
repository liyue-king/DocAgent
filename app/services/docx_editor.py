"""
====================================================================
文件用途：docx 样式修改器（原子操作 + 模板应用 + 覆盖率校验）
====================================================================
作用：
    对 python-docx 的文档执行原子级样式修改（字体/字号/加粗/
    行距/段前段后距），支持中西文字体分别设置、模板整组应用、
    修改前内存备份回滚、修改后覆盖率扫描（Validator 数据源）。
依赖：
    - python-docx（文档操作）
    - app/services/docx_parser.py（DOM 树解析与覆盖率对比）
调用方：
    - app/agents/nodes/executor.py（后续：逐条执行 Planner 生成的原子指令）
    - app/agents/nodes/validator.py（后续：扫描覆盖率判断是否重试）
说明：
    - 原子指令格式：[{"action":"set_font","para_ids":[0,1,2],"font":"黑体"}, ...]
    - 中文字体通过 w:eastAsia 属性设置（python-docx 默认设西文）。
    - EXACTLY 行距值单位为磅（如 28pt），MULTIPLE 为倍数（如 1.5）。
====================================================================
"""

from __future__ import annotations

import io  # 内存缓冲：文档克隆
import logging  # 标准库日志
from typing import Any  # 泛型类型

from docx import Document  # 文档对象
from docx.enum.text import WD_LINE_SPACING  # 行距规则枚举
from docx.oxml.ns import qn  # 命名空间查询：设置中文字体 w:eastAsia

logger = logging.getLogger(__name__)  # 模块级日志器

# 中文字体别名前缀（西文字体走常规 w:ascii/hAnsi 通道，中文字体只写 eastAsia）
_CJK_FONT_PREFIXES = (
    "宋体",
    "黑体",
    "楷体",
    "仿宋",
    "隶书",
    "幼圆",
    "微软雅黑",
    "等线",
    "华文",
    "方正",
    "思源",
    "SimSun",
    "SimHei",
    "KaiTi",
    "FangSong",
    "Microsoft YaHei",
)


def _is_cjk_font(font_name: str) -> bool:
    """判断字体名是否属于中文字体：含 CJK 字符（宋体/黑体…）或知名别名。"""
    return any("\u4e00" <= c <= "\u9fff" for c in font_name) or font_name.startswith(
        _CJK_FONT_PREFIXES
    )


# =============================================================================
# 原子操作函数
# =============================================================================


def _set_paragraph_font(para: Any, font_name: str) -> None:
    """设置段落全部 run 的字体。

    - 中文字体（宋体/黑体…）：只写 w:eastAsia 槽，不写入 w:ascii/hAnsi，
      避免中文字体名污染西文字体槽导致英文内容排版异常（fallback 字体缺失）。
    - 西文字体：走 python-docx 常规通道（w:ascii + w:hAnsi）。

    :param para: python-docx Paragraph 对象
    :param font_name: 字体名（如"黑体""宋体"或"Times New Roman"）
    """
    for run in para.runs:  # 遍历段落内所有 run
        if _is_cjk_font(font_name):
            # 中文字体 → 仅设置 w:eastAsia
            rPr = run._element.get_or_add_rPr()
            rFonts = rPr.find(qn("w:rFonts"))
            if rFonts is None:
                from lxml import etree

                rFonts = etree.SubElement(rPr, qn("w:rFonts"))
            rFonts.set(qn("w:eastAsia"), font_name)
        else:
            run.font.name = font_name  # 西文字体（w:ascii + w:hAnsi）


def _set_paragraph_font_size(para: Any, size_pt: float) -> None:
    """设置段落全部 run 的字号（磅）。

    :param para: python-docx Paragraph 对象
    :param size_pt: 字号（磅值，如 12pt 对应小四号）
    """
    from docx.shared import Pt

    for run in para.runs:
        run.font.size = Pt(size_pt)


def _set_paragraph_bold(para: Any, bold: bool) -> None:
    """设置段落全部 run 的加粗状态。"""
    for run in para.runs:
        run.font.bold = bold


def _set_paragraph_italic(para: Any, italic: bool) -> None:
    """设置段落全部 run 的斜体状态。"""
    for run in para.runs:
        run.font.italic = italic


def _set_paragraph_line_spacing(
    para: Any, rule: str, value: float | None = None
) -> None:
    """设置段落行距（单倍/1.5倍/固定值等）。

    :param para: 段落对象
    :param rule: SINGLE | DOUBLE | MULTIPLE | EXACTLY（对齐模板 config）
    :param value: MULTIPLE 时为倍数（1.5），EXACTLY/AT_LEAST 时为磅值（28）
    注意：python-docx 的 line_spacing setter 对 float 与 Length 语义不同——
          float=倍数，Length=固定磅值。EXACTLY/AT_LEAST 必须传 Pt()，否则
          会把磅值当倍数写入，读回时规则变成 MULTIPLE 导致校验失败。
    """
    from docx.shared import Pt

    pf = para.paragraph_format  # 段落格式对象
    rule_map = {
        "SINGLE": WD_LINE_SPACING.SINGLE,
        "DOUBLE": WD_LINE_SPACING.DOUBLE,
        "MULTIPLE": WD_LINE_SPACING.MULTIPLE,
        "EXACTLY": WD_LINE_SPACING.EXACTLY,
        "AT_LEAST": WD_LINE_SPACING.AT_LEAST,
    }
    spacing_rule = rule_map.get(rule.upper(), WD_LINE_SPACING.MULTIPLE)
    if rule.upper() in ("EXACTLY", "AT_LEAST") and value is not None:
        pf.line_spacing_rule = spacing_rule
        pf.line_spacing = Pt(float(value))  # 磅值 → Length
    elif rule.upper() == "MULTIPLE" and value is not None:
        pf.line_spacing_rule = spacing_rule
        pf.line_spacing = float(value)  # 倍数 → float
    else:
        pf.line_spacing_rule = spacing_rule


def _set_paragraph_space(para: Any, before_pt: int, after_pt: int) -> None:
    """设置段前距和段后距（磅）。"""
    from docx.shared import Pt

    pf = para.paragraph_format
    pf.space_before = Pt(before_pt)
    pf.space_after = Pt(after_pt)


# =============================================================================
# 操作调度
# =============================================================================


def _op_already_matches(node: dict[str, Any], op: dict[str, Any]) -> bool:
    """段落级幂等判定：当前格式已达标则跳过该段（保护段内强调格式）。

    读取口径与 docx_parser / compute_coverage 一致：
    - font / font_size：段内首个 run（多数段落的主体格式）；
    - bold：段内文本权重多数（多 run 段落的段首加粗引导语等局部强调不判整段）。
    已达标段落再整段覆盖会毁掉段内强调（如段首加粗引导语），故显式跳过。
    """
    action = op.get("action")
    if action == "set_bold":
        return bool(node.get("bold")) == bool(op.get("bold", False))
    if action == "set_font":
        font = op.get("font") or ""
        return font in {node.get("font_name") or "", node.get("font_east_asia") or ""}
    if action == "set_font_size":
        return abs((node.get("font_size_pt") or 0) - float(op.get("size_pt", 12))) <= 0.5
    return False


def apply_operations(dom: dict[str, Any], operations: list[dict[str, Any]]) -> None:
    """按原子指令队列逐条执行文档修改。

    :param dom: parse_docx 返回的 DOM 树（含 para_obj 引用）
    :param operations: Planner 生成的原子指令列表
    """
    for op in operations:  # 逐条指令
        action = op.get("action", "")  # 操作名
        para_ids = op.get("para_ids", [])  # 目标段落 ID 列表

        for pid in para_ids:  # 遍历目标段落
            para_node = dom["paragraphs"][pid]  # 段落节点（含主格式判定）
            para = para_node["para_obj"]  # 按 id 取段落对象
            if _op_already_matches(para_node, op):
                continue  # 该段此维度已达标 → 跳过（幂等，保护段内强调）
            if action == "set_font":
                _set_paragraph_font(para, op.get("font", "宋体"))
            elif action == "set_font_size":
                _set_paragraph_font_size(para, op.get("size_pt", 12))
            elif action == "set_bold":
                _set_paragraph_bold(para, op.get("bold", False))
            elif action == "set_italic":
                _set_paragraph_italic(para, op.get("italic", False))
            elif action == "set_line_spacing":
                _set_paragraph_line_spacing(para, op["rule"], op.get("value"))
            elif action == "set_paragraph_space":
                _set_paragraph_space(
                    para, op.get("space_before_pt", 0), op.get("space_after_pt", 0)
                )


def apply_template(
    doc: Document, template_config: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """按模板配置生成并执行操作队列（测试/工具辅助，生产编排走 planner 生成队列）。

    样式分组的**单一来源**是 app.agents.nodes.planner.build_style_ops —— 此处
    直接委托，避免两处样式分组逻辑漂移（此前与本文件内联分组重复实现）。

    :param doc: 已打开的 python-docx Document 对象
    :param template_config: 模板的 config 字段（含 paragraph_styles）
    :return: (DOM 树, 执行的操作队列)——DOM 树供后续覆盖率统计使用
    """
    from app.agents.nodes.planner import build_style_ops  # 样式分组单一来源
    from app.services.docx_parser import build_dom, build_dom_serial

    dom = build_dom(doc)  # 基于已有 doc 构建 DOM（修改即时生效）
    operations = build_style_ops(template_config, build_dom_serial(dom))
    apply_operations(dom, operations)
    return dom, operations


# =============================================================================
# 备份与回滚
# =============================================================================


def backup_doc(file_path: str) -> tuple[Document | None, bytes | None]:
    """打开文档并创建内存备份（BytesIO 序列化）。

    :param file_path: docx 文件路径
    :return: (文档对象, 备份字节)；文件损坏/不可读/备份为空时返回
             (None, None)（调用方须判空走失败分支，勿解包使用）
    """
    try:
        doc = Document(file_path)  # 打开原文档
        buf = io.BytesIO()  # 内存缓冲区
        doc.save(buf)  # 序列化到内存
        if buf.tell() == 0:  # 序列化无输出（防御，理论上不发生）
            logger.warning("[docx_editor] backup_doc 序列化输出为空: %s", file_path)
            return None, None
        buf.seek(0)  # 重置读取游标
        return doc, buf.getvalue()  # 返回 doc + 备份字节
    except Exception as exc:  # 文件损坏/权限/空文件 → (None, None)
        logger.warning("[docx_editor] backup_doc 打开/备份失败: %s", exc)
        return None, None


def restore_doc(backup_bytes: bytes | None) -> Document:
    """从备份字节重建文档对象（回滚用）。

    :param backup_bytes: backup_doc 返回的备份字节
    :return: 原始文档对象
    :raises ValueError: 备份字节为空（不可回滚）
    """
    if not backup_bytes:
        raise ValueError("备份字节为空，无法回滚")
    return Document(io.BytesIO(backup_bytes))


# =============================================================================
# 覆盖率计算（Validator 数据源）
# =============================================================================


def compute_coverage(
    doc: Document,
    template_config: dict[str, Any],
    llm_overrides: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """扫描文档样式覆盖率（Validator 判断是否重试的入参）。

    算法：基于已有 doc 构建 DOM → 逐段对比 **五项维度**（字体/字号/加粗/
    行距规则与值/段前段后距）与模板目标值 → 覆盖率 = 匹配段落数 / 可评估段落总数。
    v5.2 扩展：行距与段间距同样参与覆盖计算，任一维度不匹配即判 missed，
    避免此前仅查三项导致的"假通过"。missed 明细携带 expected/actual/reason，
    供 Planner 做增量修补。

    v6.2：**用户个性化覆盖（llm_overrides）成为验收基准**——被 LLM 覆盖的
    (para_id, dim) 按用户目标值对比，不再按模板值（否则重试闭环会把
    用户需求"修回"模板）。未覆盖的段维仍按模板验收。

    :param doc: 修改后的文档对象（在内存中）
    :param template_config: 模板的 config
    :param llm_overrides: {para_id: {dim: 用户目标值}}（Planner LLM 路径产出）
    :return: {"coverage": 0.95, "total": 10, "matched": 8, "missed": [...],
              "passed": True}；missed 元素含 para_id/style/expected/actual/reason
    """
    from app.services.docx_parser import build_dom

    # 基于已有 doc 构建 DOM（不重新打开文件）
    new_dom = build_dom(doc)

    styles = template_config.get("paragraph_styles", {})
    overrides = llm_overrides or {}
    total = 0  # 可评估的段落总数
    matched = 0  # 样式匹配的段落数
    missed: list[dict[str, Any]] = []  # 未匹配的段落详情

    for p in new_dom["paragraphs"]:
        s = p["style"]
        if s == "normal" and p.get("keep_format"):
            continue  # 保留原格式段落不参与覆盖率校验（不会被模板覆盖）
        base_target = styles.get(s)  # 模板目标样式
        if base_target is None:
            continue  # 非 key 样式（other）不参与评估
        if p.get("run_count", 0) == 0:
            continue  # 空段落无可排版内容（无 run，字体/字号无法施加），不参与评估
        if p.get("has_image") and not p.get("text"):
            continue  # 纯图片/公式段（无文本）：无可排版内容，整段不参与评估
        total += 1

        # v6.2：用户个性化覆盖合成到验收目标（被 LLM 覆盖的段维按用户值验收，
        # 其余维度仍按模板值；expected 明细自动展示用户目标）
        target = _apply_overrides(base_target, overrides.get(p["id"]) or {})

        failed_dims: list[str] = []  # 不匹配的维度名列表
        # ---- 1. 字体：目标字体命中西文字体或中文字体任一即可 ----
        target_font = (target.get("font_name") or "").strip()
        actual_fonts = {p.get("font_name") or "", p.get("font_east_asia") or ""}
        if target_font not in actual_fonts:
            failed_dims.append("font")
        # ---- 2. 字号：允许 0.5pt 误差 ----
        if abs((p["font_size_pt"] or 0) - target.get("font_size_pt", 0)) > 0.5:
            failed_dims.append("font_size")
        # ---- 3. 加粗 ----
        if p["bold"] != target.get("bold", False):
            failed_dims.append("bold")
        # ---- 4. 行距：规则与值均需匹配（v5.2 新增）----
        # 含图片/形状/公式的段落豁免：EXACTLY 固定行距会裁切高于行高的
        # 图片/公式（Word 渲染行为，不可逆），planner 也不对该段生成行距指令
        if not p.get("has_image") and not _line_spacing_match(p, target):
            failed_dims.append("line_spacing")
        # ---- 5. 段前段后距：允许 0.5pt 误差（v5.2 新增）----
        if not _paragraph_space_match(p, target):
            failed_dims.append("paragraph_space")

        if not failed_dims:
            matched += 1
        else:
            missed.append(
                {
                    "para_id": p["id"],
                    "style": s,
                    "text_preview": p["text"][:50],
                    "expected": {
                        "font_name": target.get("font_name"),
                        "font_size_pt": target.get("font_size_pt"),
                        "bold": target.get("bold"),
                        "line_spacing_rule": target.get("line_spacing_rule"),
                        "line_spacing_value": target.get("line_spacing_value"),
                        "space_before_pt": target.get("space_before_pt"),
                        "space_after_pt": target.get("space_after_pt"),
                    },
                    "actual": {
                        "font_name": p.get("font_name"),
                        "font_east_asia": p.get("font_east_asia"),
                        "font_size_pt": p.get("font_size_pt"),
                        "bold": p.get("bold"),
                        "line_spacing_rule": p.get("line_spacing_rule"),
                        "line_spacing_value": p.get("line_spacing_value"),
                        "space_before_pt": p.get("space_before_pt"),
                        "space_after_pt": p.get("space_after_pt"),
                    },
                    "reason": ",".join(failed_dims),  # 逗号分隔的不匹配维度
                }
            )

    coverage = matched / total if total > 0 else 1.0  # 无段落视为 100%
    # passed 判断：≥98% 通过（对齐蓝图成功验收线；100% 为重试触发线见 Validator）
    passed = coverage >= 0.98

    return {
        "coverage": round(coverage, 4),
        "total": total,
        "matched": matched,
        "missed": missed,
        "passed": passed,
    }


def _apply_overrides(
    target: dict[str, Any], para_overrides: dict[str, Any]
) -> dict[str, Any]:
    """把用户个性化覆盖（llm_overrides）合成进模板验收目标。

    仅覆盖声明过的维度（key 存在才覆盖），未覆盖维度保持模板值。

    :param target: 模板目标样式配置（paragraph_styles[style]）
    :param para_overrides: {dim: 用户目标值}（Planner LLM 路径产出）
    :return: 合成后的验收目标（expected 明细可正确展示用户目标）
    """
    merged = dict(target)
    mapping = {
        "font": "font_name",
        "font_size": "font_size_pt",
        "bold": "bold",
        "line_spacing_rule": "line_spacing_rule",
        "line_spacing_value": "line_spacing_value",
        "space_before_pt": "space_before_pt",
        "space_after_pt": "space_after_pt",
    }
    for dim, key in mapping.items():
        if dim in para_overrides:
            merged[key] = para_overrides[dim]
    return merged


def _line_spacing_match(p: dict[str, Any], target: dict[str, Any]) -> bool:
    """比对行距：规则必须一致，值（存在时）需在误差范围内。

    :param p: DOM 段落节点（含 line_spacing_rule / line_spacing_value）
    :param target: 模板目标样式配置
    :return: 是否匹配
    """
    rule_ok = (p.get("line_spacing_rule") or "").upper() == (
        target.get("line_spacing_rule") or ""
    ).upper()
    if not rule_ok:
        return False
    t_value = target.get("line_spacing_value")  # 模板目标值（可空，如 SINGLE）
    a_value = p.get("line_spacing_value")
    if t_value is None:  # 模板未要求具体值（如 SINGLE），仅比对规则
        return True
    if a_value is None:  # 规则匹配但实际值缺失
        return False
    tol = 0.5 if t_value > 3 else 0.01  # EXACTLY 磅值用 0.5pt，MULTIPLE 倍数用 0.01
    return abs(a_value - t_value) <= tol


def _paragraph_space_match(p: dict[str, Any], target: dict[str, Any]) -> bool:
    """比对段前/段后距（磅，允许 0.5pt 误差）。

    :param p: DOM 段落节点（含 space_before_pt / space_after_pt）
    :param target: 模板目标样式配置
    :return: 是否匹配
    """
    t_before = target.get("space_before_pt", 0) or 0
    t_after = target.get("space_after_pt", 0) or 0
    a_before = p.get("space_before_pt") or 0
    a_after = p.get("space_after_pt") or 0
    return abs(a_before - t_before) <= 0.5 and abs(a_after - t_after) <= 0.5
