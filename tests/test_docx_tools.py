"""docx 工具链测试：解析 / 样式修改 / 覆盖率 / 备份回滚（B2 回归）。"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from docx import Document

from app.services.docx_editor import (
    apply_template,
    backup_doc,
    compute_coverage,
    restore_doc,
)
from app.services.docx_parser import parse_docx


def _seed_config() -> dict:
    """读取脚本内嵌模板配置（学术论文模板），供样式修改测试。"""
    seed_path = Path(__file__).resolve().parent.parent / "scripts" / "seed_templates.json"
    seeds = json.loads(seed_path.read_text(encoding="utf-8"))
    return seeds[0]["config"]


def test_parse_docx_styles(test_docx_path: str) -> None:
    """解析器：识别多级标题与正文样式。"""
    dom = parse_docx(test_docx_path)
    assert dom["paragraph_count"] >= 4
    styles = {p["style"] for p in dom["paragraphs"]}
    assert {"heading_1", "heading_2", "heading_3", "normal"} <= styles


def test_apply_template_and_coverage(test_docx_path: str) -> None:
    """样式修改器：apply_template 产出原子指令，覆盖率 ≥ 98%。"""
    config = _seed_config()
    doc = Document(test_docx_path)
    _, ops = apply_template(doc, config)
    assert isinstance(ops, list)
    cov = compute_coverage(doc, config)
    assert cov["coverage"] >= 0.98
    assert cov["passed"] > 0


def test_backup_restore_roundtrip(test_docx_path: str) -> None:
    """备份 → 回滚：恢复的文档可保存并重新解析（正常路径）。"""
    doc, backup_bytes = backup_doc(test_docx_path)
    assert doc is not None and backup_bytes
    restored = restore_doc(backup_bytes)
    buf = io.BytesIO()
    restored.save(buf)
    assert len(buf.getvalue()) > 0
    assert parse_docx(test_docx_path)["paragraph_count"] >= 4


def test_backup_doc_corrupt_returns_none(tmp_path: Path) -> None:
    """B2 回归：损坏 docx → backup_doc 返回 (None, None) 而非抛异常。"""
    bad = tmp_path / "broken.docx"
    bad.write_bytes(b"this is not a valid docx")
    doc, backup_bytes = backup_doc(str(bad))
    assert doc is None and backup_bytes is None


def test_restore_doc_none_raises() -> None:
    """B2 回归：restore_doc(None) 显式抛 ValueError（防御空备份）。"""
    with pytest.raises(ValueError):
        restore_doc(None)
