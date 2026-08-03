"""
====================================================================
文件用途：docx 文档解析器（DOM 树生成）
====================================================================
作用：
    用 python-docx 解析 .docx 文档，提取段落样式/字体信息，
    生成标准化的 DOM 树结构（供 Planner 决策和 Executor 定位）。
依赖：
    - python-docx（文档读取）
调用方：
    - app/services/docx_editor.py（按段落 ID 执行修改）
    - app/agents/nodes/planner.py（后续：根据 DOM 树规划操作）
输出结构：
    {"paragraphs": [{"id":0, "style":"heading_1", "style_raw":"标题 1",
      "text":"...", "font_name":"宋体", "font_size_pt":12, "bold":False,
      "para_obj":<Paragraph>}], "paragraph_count":10, "tables_count":0}
说明：
    - 样式名做中英文规范化映射（"标题 1"→"heading_1", "Heading 1"→"heading_1" 等）。
    - 保留 python-docx 的原始 Paragraph 对象引用（para_obj），
      编辑器通过段落 id 取值后直接操作原对象，无需二次查找。
====================================================================
"""

from __future__ import annotations

import re  # 正则：样式名映射
from typing import Any  # 泛型类型

from docx import Document  # python-docx 文档对象
from docx.oxml.ns import qn  # 命名空间查询（读取 w:eastAsia 中文字体）
from docx.shared import Length  # 长度对象（行距/段距读取）


def _normalize_style(style_name: str) -> str:
    """将 Word 样式名统一映射为内部键（heading_1|heading_2|heading_3|normal|other）。

    :param style_name: python-docx 返回的 style.name（如 "Heading 1", "标题 1", "Normal"）
    :return: 归一化样式标识
    """
    name = style_name.strip().lower()  # 转小写去空格，方便匹配
    # 匹配中文样式名：标题 1 / 标题 2 / 标题 3 / 正文 / 副标题
    if re.search(r"标题\s*1|heading\s*1|head\s*1", name):
        return "heading_1"
    if re.search(r"标题\s*2|heading\s*2|head\s*2", name):
        return "heading_2"
    if re.search(r"标题\s*3|heading\s*3|head\s*3", name):
        return "heading_3"
    if re.search(r"标题\s*4|heading\s*4|head\s*4", name):
        return "heading_3"  # 四级标题降级为三级
    if re.search(r"正文|normal|body", name):
        return "normal"
    if re.search(r"副标题|subtitle", name):
        return "heading_2"  # 副标题视为二级标题
    # 无法匹配的样式归为 other（如列表/引用/题注）
    return "other"


def _read_east_asia_font(run: Any) -> str | None:
    """读取 run 的中文字体（w:rFonts/w:eastAsia），未设置返回 None。

    :param run: python-docx Run 对象
    :return: 中文字体名（如"宋体"）；未设置返回 None
    """
    rPr = run._element.rPr  # run 的属性容器（可能为 None）
    if rPr is None:
        return None
    rFonts = rPr.find(qn("w:rFonts"))  # 字体声明元素
    if rFonts is None:
        return None
    return rFonts.get(qn("w:eastAsia"))  # 中文字体名


def _read_line_spacing(para: Any) -> tuple[str | None, float | None]:
    """读取段落行距规则与值。

    :param para: python-docx Paragraph 对象
    :return: (规则字符串, 值)。规则取值 SINGLE/DOUBLE/MULTIPLE/EXACTLY/AT_LEAST；
             SINGLE 值为 1.0，DOUBLE 为 2.0，MULTIPLE 为倍数，EXACTLY/AT_LEAST 为磅值
    """
    pf = para.paragraph_format
    rule_enum = pf.line_spacing_rule  # WD_LINE_SPACING 枚举或 None
    if rule_enum is None:
        return None, None
    rule = rule_enum.name  # 如 "MULTIPLE" / "SINGLE" / "EXACTLY" / "ONE_POINT_FIVE"
    ls = pf.line_spacing  # Length（磅）或 float（倍数）或 None
    # 归一化：Word 内置 1.5/2.5 倍行距在 OOXML 中是 w:lineRule=auto 的
    # 特殊倍数，python-docx 读回为 ONE_POINT_FIVE / TWO_POINT_FIVE，
    # 语义等同模板配置中的 MULTIPLE + 对应倍数值，需归一化后才可比对。
    if rule in ("ONE_POINT_FIVE", "TWO_POINT_FIVE"):
        return "MULTIPLE", (1.5 if rule == "ONE_POINT_FIVE" else 2.5)
    if rule == "SINGLE":
        return rule, 1.0
    if rule == "DOUBLE":
        return rule, 2.0
    if isinstance(ls, Length):  # EXACTLY / AT_LEAST：长度对象（磅）
        return rule, round(ls.pt, 2)
    if ls is not None:  # MULTIPLE：倍数
        return rule, float(ls)
    return rule, None


def _read_paragraph_space(para: Any) -> tuple[float, float]:
    """读取段落段前距与段后距（磅）。

    :param para: python-docx Paragraph 对象
    :return: (space_before_pt, space_after_pt)；未设置视为 0.0
    """
    pf = para.paragraph_format
    sb = pf.space_before
    sa = pf.space_after
    return (round(sb.pt, 2) if sb is not None else 0.0), (
        round(sa.pt, 2) if sa is not None else 0.0
    )


def build_dom_serial(dom: dict[str, Any]) -> dict[str, Any]:
    """从完整 DOM 提取可序列化部分（剔除 para_obj 引用）。

    供 LangGraph Checkpointer（P1）/ 状态快照持久化使用——para_obj 是
    python-docx 对象引用，无法 JSON 序列化，故单独抽出纯数据层。

    :param dom: build_dom / parse_docx 返回的完整 DOM 树
    :return: 仅含纯数据字段的 DOM（paragraphs 不含 para_obj）
    """
    serial_paragraphs: list[dict[str, Any]] = []
    for p in dom["paragraphs"]:
        serial_paragraphs.append(
            {
                "id": p["id"],
                "style": p["style"],
                "style_raw": p["style_raw"],
                "text": p["text"],
                "font_name": p["font_name"],
                "font_east_asia": p["font_east_asia"],
                "font_size_pt": p["font_size_pt"],
                "bold": p["bold"],
                "line_spacing_rule": p["line_spacing_rule"],
                "line_spacing_value": p["line_spacing_value"],
                "space_before_pt": p["space_before_pt"],
                "space_after_pt": p["space_after_pt"],
                "run_count": p["run_count"],
            }
        )
    return {
        "paragraphs": serial_paragraphs,
        "paragraph_count": dom["paragraph_count"],
        "tables_count": dom["tables_count"],
    }


def parse_docx(file_path: str) -> dict[str, Any]:
    """解析 docx 文件并生成 DOM 树（从文件路径打开）。

    :param file_path: .docx 文件的本地路径
    :return: DOM 树字典
    """
    return build_dom(Document(file_path))


def build_dom(doc: Document) -> dict[str, Any]:
    """基于已有 Document 实例构建 DOM 树（para_obj 与传入 doc 共享引用）。

    与 parse_docx 的区别：不重新打开文件，para_obj 直接引用传入 doc.paragraphs。
    这样 apply_template 修改 DOM 中的 para_obj 时，原 doc 对象也同步更新。

    :param doc: python-docx Document 实例
    :return: DOM 树字典
    """
    paragraphs: list[dict[str, Any]] = []  # 段落列表

    for idx, para in enumerate(doc.paragraphs):
        # 获取样式名（可能为 None）
        style_name = para.style.name if para.style and para.style.name else ""
        style_key = _normalize_style(style_name)

        # 提取段落文字（取纯文本）
        text = para.text.strip()

        # ----- 提取字体信息：取第一个 run 的格式（多数段落只有 1 个 run）-----
        if para.runs:
            run = para.runs[0]  # 首个 run 代表段落主体格式
            font_name = run.font.name  # 西文字体
            font_size = run.font.size
            font_size_pt = round(font_size.pt, 1) if font_size else 0  # 字号（磅）
            bold = run.font.bold is True  # 是否加粗（排除 None 和 False）
            font_east_asia = _read_east_asia_font(run)  # 中文字体（w:eastAsia）
        else:
            font_name = None
            font_size_pt = 0
            bold = False
            font_east_asia = None

        # ----- 提取行距与段间距（Validator 五项校验的另两维数据源）-----
        line_spacing_rule, line_spacing_value = _read_line_spacing(para)
        space_before_pt, space_after_pt = _read_paragraph_space(para)

        # 构造段落节点
        node = {
            "id": idx,  # 段落序号（0-based）
            "style": style_key,  # 归一化样式标识
            "style_raw": style_name,  # 原始样式名（调试用）
            "text": text[:200],  # 文本前 200 字（预览用）
            "font_name": font_name,  # 西文字体名（如"Calibri"）
            "font_east_asia": font_east_asia,  # 中文字体名（如"宋体"，可为 None）
            "font_size_pt": font_size_pt,  # 字号（磅）
            "bold": bold,  # 是否加粗
            "line_spacing_rule": line_spacing_rule,  # 行距规则（SINGLE/MULTIPLE/EXACTLY...）
            "line_spacing_value": line_spacing_value,  # 行距值（倍数或磅值）
            "space_before_pt": space_before_pt,  # 段前距（磅）
            "space_after_pt": space_after_pt,  # 段后距（磅）
            "run_count": len(para.runs),  # run 数量（0=空段落，无可排版内容）
            "para_obj": para,  # python-docx 段落对象引用（编辑器操作）
        }
        paragraphs.append(node)

    # 统计基本信息
    tables_count = len(doc.tables)  # 表格数量（P0 不处理表格）

    return {
        "paragraphs": paragraphs,
        "paragraph_count": len(paragraphs),
        "tables_count": tables_count,
    }
