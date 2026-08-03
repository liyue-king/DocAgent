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
from typing import Any  # 泛型类型

from docx import Document  # 文档对象
from docx.enum.text import WD_LINE_SPACING  # 行距规则枚举
from docx.oxml.ns import qn  # 命名空间查询：设置中文字体 w:eastAsia

# =============================================================================
# 原子操作函数
# =============================================================================


def _set_paragraph_font(para: Any, font_name: str) -> None:
    """设置段落全部 run 的中西文字体（西文=font.name，中文=eastAsia）。

    :param para: python-docx Paragraph 对象
    :param font_name: 字体名（如"黑体""宋体"）
    """
    for run in para.runs:  # 遍历段落内所有 run
        run.font.name = font_name  # 西文字体
        # 设置中文字体：通过 XML element 的 rPr/rFonts/w:eastAsia 属性
        rPr = run._element.get_or_add_rPr()
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            from lxml import etree

            rFonts = etree.SubElement(rPr, qn("w:rFonts"))
        rFonts.set(qn("w:eastAsia"), font_name)


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


def apply_operations(dom: dict[str, Any], operations: list[dict[str, Any]]) -> None:
    """按原子指令队列逐条执行文档修改。

    :param dom: parse_docx 返回的 DOM 树（含 para_obj 引用）
    :param operations: Planner 生成的原子指令列表
    """
    for op in operations:  # 逐条指令
        action = op.get("action", "")  # 操作名
        para_ids = op.get("para_ids", [])  # 目标段落 ID 列表

        for pid in para_ids:  # 遍历目标段落
            para = dom["paragraphs"][pid]["para_obj"]  # 按 id 取段落对象
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
    """根据模板配置生成并执行操作队列（高层方法，供 Planner/Executor 使用）。

    内部调用 build_dom 构建 DOM（段落引用与传入 doc 共享，修改即时生效）。

    :param doc: 已打开的 python-docx Document 对象
    :param template_config: 模板的 config 字段（含 paragraph_styles）
    :return: (DOM 树, 执行的操作队列)——DOM 树供后续覆盖率统计使用
    """
    from app.services.docx_parser import build_dom

    dom = build_dom(doc)  # 基于已有 doc 构建 DOM（修改即时生效）
    styles = template_config.get("paragraph_styles", {})  # 提取样式配置
    operations: list[dict[str, Any]] = []  # 操作队列

    # 按样式分组：遍历每个段落，根据其 heading_1/2/3/normal 生成操作
    style_group: dict[str, list[int]] = {}  # {style: [para_id, ...]}
    for p in dom["paragraphs"]:
        s = p["style"]
        if s in ("heading_1", "heading_2", "heading_3", "normal"):
            style_group.setdefault(s, []).append(p["id"])

    # 对每种样式生成一组原子操作
    for style_key, para_ids in style_group.items():
        cfg = styles.get(style_key)
        if cfg is None:
            continue  # 模板中未定义该样式，跳过
        ops: list[dict[str, Any]] = [
            {"action": "set_font", "para_ids": para_ids, "font": cfg["font_name"]},
            {
                "action": "set_font_size",
                "para_ids": para_ids,
                "size_pt": cfg["font_size_pt"],
            },
            {
                "action": "set_bold",
                "para_ids": para_ids,
                "bold": cfg.get("bold", False),
            },
            {
                "action": "set_line_spacing",
                "para_ids": para_ids,
                "rule": cfg["line_spacing_rule"],
                "value": cfg.get("line_spacing_value"),
            },
            {
                "action": "set_paragraph_space",
                "para_ids": para_ids,
                "space_before_pt": cfg.get("space_before_pt", 0),
                "space_after_pt": cfg.get("space_after_pt", 0),
            },
        ]
        operations.extend(ops)

    # 执行整组操作
    apply_operations(dom, operations)
    return dom, operations


# =============================================================================
# 备份与回滚
# =============================================================================


def backup_doc(file_path: str) -> tuple[Document, bytes]:
    """打开文档并创建内存备份（BytesIO 序列化）。

    :param file_path: docx 文件路径
    :return: (文档对象, 备份字节)——修改失败时用 backup 重建 doc
    """
    doc = Document(file_path)  # 打开原文档
    buf = io.BytesIO()  # 内存缓冲区
    doc.save(buf)  # 序列化到内存
    buf.seek(0)  # 重置读取游标
    return doc, buf.getvalue()  # 返回 doc + 备份字节


def restore_doc(backup_bytes: bytes) -> Document:
    """从备份字节重建文档对象（回滚用）。

    :param backup_bytes: backup_doc 返回的备份字节
    :return: 原始文档对象
    """
    return Document(io.BytesIO(backup_bytes))


# =============================================================================
# 覆盖率计算（Validator 数据源）
# =============================================================================


def compute_coverage(doc: Document, template_config: dict[str, Any]) -> dict[str, Any]:
    """扫描文档样式覆盖率（Validator 判断是否重试的入参）。

    算法：基于已有 doc 构建 DOM → 逐段对比 **五项维度**（字体/字号/加粗/
    行距规则与值/段前段后距）与模板目标值 → 覆盖率 = 匹配段落数 / 可评估段落总数。
    v5.2 扩展：行距与段间距同样参与覆盖计算，任一维度不匹配即判 missed，
    避免此前仅查三项导致的"假通过"。missed 明细携带 expected/actual/reason，
    供 Planner 做增量修补。

    :param doc: 修改后的文档对象（在内存中）
    :param template_config: 模板的 config
    :return: {"coverage": 0.95, "total": 10, "matched": 8, "missed": [...],
              "passed": True}；missed 元素含 para_id/style/expected/actual/reason
    """
    from app.services.docx_parser import build_dom

    # 基于已有 doc 构建 DOM（不重新打开文件）
    new_dom = build_dom(doc)

    styles = template_config.get("paragraph_styles", {})
    total = 0  # 可评估的段落总数
    matched = 0  # 样式匹配的段落数
    missed: list[dict[str, Any]] = []  # 未匹配的段落详情

    for p in new_dom["paragraphs"]:
        s = p["style"]
        target = styles.get(s)  # 目标样式
        if target is None:
            continue  # 非 key 样式（other）不参与评估
        if p.get("run_count", 0) == 0:
            continue  # 空段落无可排版内容（无 run，字体/字号无法施加），不参与评估
        total += 1

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
        if not _line_spacing_match(p, target):
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
