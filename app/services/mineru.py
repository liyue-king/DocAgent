"""
====================================================================
文件用途：MinerU 文档解析服务（OpenXLab API，可选增强）
====================================================================
作用：
    用 MinerU 解析上传文档（docx/pdf/图片等）为 markdown 文本，
    支持图片提取（图片下载存 MinIO）。作为知识库上传的优先解析
    路径，失败/未配置 key 时由调用方降级回本地正则提取。
流程：
    1. POST /file-urls/batch        —— 申请签名上传 URL
    2. PUT 上传文件到签名 URL
    3. POST /extract/task           —— 提交解析任务（vlm 模型）
    4. GET  /extract/task/{id}      —— 轮询直至 done（默认 120s 超时）
    5. 下载结果 zip → 提取 .md 文本，images/ 图片存 MinIO 并替换引用
配置（app.config.settings）：
    - mineru_api_key        MinerU token（空 = 未启用）
    - mineru_base_url       API 基址（默认 https://mineru.net/api/v4）
    - mineru_timeout_seconds 轮询总超时（默认 120）
调用方：
    - app/api/knowledge.py（upload_my_doc：MinerU 优先，None → 本地提取）
====================================================================
"""

from __future__ import annotations

import io  # zip 内存解压
import logging  # 标准库日志
import re  # markdown 图片引用替换
import time  # 轮询超时控制
import zipfile  # 结果 zip 解压
from datetime import datetime  # MinIO 图片路径日期
from typing import Any  # 泛型类型
from urllib.parse import quote  # 文件名 URL 编码

import httpx  # HTTP 客户端

from app.config import settings  # MinerU 配置
from app.services.storage import storage  # 图片存 MinIO

logger = logging.getLogger(__name__)  # 模块级日志器

# 任务状态（官方文档）：pending/running/converting/uploading/done/failed
_DONE = "done"
_FAILED = "failed"
_HTTP_TIMEOUT = 30  # 单次 HTTP 请求超时（秒）
_POLL_INTERVAL_SECONDS = 3  # 轮询间隔

_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(images/([^)\s]+)\)")  # md 图片引用


def _headers() -> dict[str, str]:
    """统一认证头。"""
    return {
        "Authorization": f"Bearer {settings.mineru_api_key}",
        "Content-Type": "application/json",
    }


def _request_upload_url(filename: str) -> tuple[str, str]:
    """申请签名上传 URL，返回 (file_url, upload_url)。"""
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.post(
            f"{settings.mineru_base_url}/file-urls/batch",
            headers=_headers(),
            json={"filenames": [filename]},
        )
        resp.raise_for_status()
        body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"file-urls/batch 返回错误: {body.get('msg', body)}")
    item = (body.get("data") or [{}])[0]
    file_url = item.get("file_url") or item.get("url")
    upload_url = item.get("upload_url") or item.get("presignedUrl")
    if not file_url or not upload_url:
        raise RuntimeError(f"file-urls/batch 响应缺少上传信息: {item}")
    return file_url, upload_url


def _upload_file(upload_url: str, data: bytes) -> None:
    """PUT 上传文件（不带 Content-Type，按官方要求）。"""
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.put(upload_url, content=data, headers={"Accept": "*/*"})
        resp.raise_for_status()


def _create_task(file_url: str, filename: str) -> str:
    """提交解析任务，返回 task_id。"""
    payload: dict[str, Any] = {
        "url": file_url,
        "model_version": "vlm",  # 推荐模型：版面/公式/表格识别更准
        "is_ocr": True,  # 扫描件也提取
        "language": "ch",
        "enable_formula": True,
        "enable_table": True,
        "data_id": filename[:128],
    }
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.post(
            f"{settings.mineru_base_url}/extract/task", headers=_headers(), json=payload
        )
        resp.raise_for_status()
        body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"extract/task 返回错误: {body.get('msg', body)}")
    return (body.get("data") or {}).get("task_id", "")


def _poll_task(task_id: str) -> str:
    """轮询任务直至 done，返回 full_zip_url；failed/超时抛异常。"""
    deadline = time.monotonic() + settings.mineru_timeout_seconds
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        while time.monotonic() < deadline:
            resp = client.get(
                f"{settings.mineru_base_url}/extract/task/{task_id}",
                headers=_headers(),
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != 0:
                raise RuntimeError(f"任务查询错误: {body.get('msg', body)}")
            data = body.get("data") or {}
            state = data.get("state", "")
            if state == _DONE:
                zip_url = data.get("full_zip_url", "")
                if not zip_url:
                    raise RuntimeError("任务完成但缺少 full_zip_url")
                return zip_url
            if state == _FAILED:
                raise RuntimeError(f"解析失败: {data.get('err_msg', '未知错误')}")
            time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"MinerU 解析超时（>{settings.mineru_timeout_seconds}s），任务 {task_id}"
    )


def _store_images(zip_data: bytes, zip_name: str) -> dict[str, str]:
    """把结果 zip 中 images/ 目录的图片存 MinIO，返回 {原文件名: minio_key}。"""
    keys: dict[str, str] = {}
    prefix = f"knowledge/{datetime.now():%Y/%m/%d}/mineru/{zip_name[:16]}"
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for name in zf.namelist():
                if name.startswith("images/") and not name.endswith("/"):
                    try:
                        key = f"{prefix}/{quote(name.split('/')[-1])}"
                        storage.upload_bytes(
                            zf.read(name),
                            bucket=settings.minio_knowledge_bucket,
                            key=key,
                        )
                        keys[name.split("/")[-1]] = key
                    except Exception as exc:  # 单图失败不阻断
                        logger.warning("[mineru] 图片 %s 上传失败: %s", name, exc)
    except zipfile.BadZipFile as exc:
        logger.warning("[mineru] 结果 zip 损坏: %s", exc)
    return keys


def _extract_markdown(zip_data: bytes) -> str:
    """从结果 zip 提取全部 .md 文本（多文件拼接，按文件名排序）。"""
    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        names = sorted(n for n in zf.namelist() if n.lower().endswith(".md"))
        for name in names:
            parts.append(zf.read(name).decode("utf-8", errors="ignore"))
    return "\n\n".join(parts)


def extract_text(filename: str | None, data: bytes) -> str | None:
    """MinerU 提取文档为 markdown 文本（含图片存 MinIO）。

    :param filename: 原始文件名
    :param data: 文件字节
    :return: markdown 文本；未配置 key / 任何失败 → None（调用方降级本地提取）
    """
    if not settings.mineru_api_key or not data:
        return None
    name = (filename or "").strip()
    if not name:
        return None
    try:
        file_url, upload_url = _request_upload_url(name)
        _upload_file(upload_url, data)
        task_id = _create_task(file_url, name)
        if not task_id:
            raise RuntimeError("提交任务未返回 task_id")
        zip_url = _poll_task(task_id)
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(zip_url)
            resp.raise_for_status()
            zip_data = resp.content
        text = _extract_markdown(zip_data)
        image_keys = _store_images(zip_data, name)
        # 图片引用替换为 MinIO key（保留位置信息，便于追溯原图）
        if image_keys:
            def _replace(m: re.Match[str]) -> str:
                key = image_keys.get(m.group(2), "")
                return f"[图: {m.group(2)}]({key})" if key else m.group(0)
            text = _IMAGE_PATTERN.sub(_replace, text)
        logger.info(
            "[mineru] 解析成功: %s（%d 字，%d 张图片入库）",
            name,
            len(text),
            len(image_keys),
        )
        return text.strip() or None
    except Exception as exc:  # 网络/API/解析任何失败 → None（降级信号）
        logger.warning("[mineru] 解析失败，降级本地提取: %s", exc)
        return None
