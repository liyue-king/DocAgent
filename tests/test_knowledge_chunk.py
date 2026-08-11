"""知识库切块测试（纯函数，无外部依赖）。"""

from __future__ import annotations

from app.services.knowledge import chunk_text


def test_chunk_empty() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_chunk_short_text_single() -> None:
    assert chunk_text("一段文本") == ["一段文本"]


def test_chunk_long_paragraph_split_by_sentence() -> None:
    """超长段落按句切分，块长不超过 chunk_size + overlap 上限。"""
    text = "第一句内容。" + "第二句内容。" * 100
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= 600 + 100 for c in chunks)


def test_chunk_dedup() -> None:
    """相同内容段落合并去重（前 50 字符指纹）。"""
    assert len(chunk_text("同一段内容。\n同一段内容。")) == 1


def test_chunk_long_text_content_complete() -> None:
    """长文档切出多块，内容完整无丢失（拼接后原文全部出现）。"""
    text = "。".join(f"段落{i}内容" for i in range(300))
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    joined = "".join(chunks)
    for i in range(300):
        assert f"段落{i}内容" in joined


def test_chunk_overlap_when_full() -> None:
    """超长无标点段落（单句 > chunk_size）触发 overlap：后块以先前块尾部开头。"""
    text = ("甲" * 2800) + ("乙" * 200)
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    assert chunks[1].startswith(chunks[0][-100:])
