"""
====================================================================
文件用途：MinIO 对象存储服务（文件资产层）
====================================================================
作用：
    封装 MinIO 的上传/下载/备份/预签名 URL 操作，供 Executor（备份）、
    SuccessNode / ErrorNode（输出落库）等智能体节点调用。
依赖：
    - minio（S3 兼容客户端，已加入 pyproject.toml）
    - app.config.settings（endpoint / 密钥 / 桶名）
调用方：
    - app/agents/nodes/executor.py（修改前自动备份原文件）
    - app/agents/nodes/success.py / error.py（输出文件上传）
    - app/api/routes.py（后续：预签名下载 URL）
说明：
    - 桶访问策略为 Private，下载走 5 分钟预签名 URL（防盗链）。
    - 所有方法在 MinIO 不可用时抛出 StorageUnavailable，由调用方
      降级为“内存/本地备份”策略，保证文档绝不丢失。
====================================================================
"""

from __future__ import annotations

import io  # 内存缓冲（upload_bytes 用）
import logging  # 标准库日志
from typing import Any  # 泛型类型

from app.config import settings  # MinIO 连接配置

logger = logging.getLogger(__name__)  # 模块级日志器


class StorageUnavailable(Exception):
    """MinIO 不可用时抛出的异常（调用方捕获后走降级策略）。"""


class MinioStorage:
    """MinIO 对象存储封装（延迟连接，首次使用时初始化）。"""

    def __init__(self) -> None:
        """延迟创建客户端：真正用到 MinIO 时才连接，避免服务启动即失败。"""
        self._client: Any | None = None
        self._connected: bool | None = None  # None=未探测

    # ------------------------------------------------------------------
    # 客户端连接
    # ------------------------------------------------------------------
    def _get_client(self) -> Any:
        """获取（并按需创建）MinIO 客户端，连接失败抛 StorageUnavailable。

        :raises StorageUnavailable: 依赖缺失或连接失败
        """
        if self._client is not None:
            return self._client  # 已连接，直接复用
        try:
            from minio import Minio  # 延迟导入，避免依赖缺失即崩溃
        except ImportError as exc:  # minio 包未安装
            raise StorageUnavailable(f"minio 客户端未安装: {exc}") from exc

        try:
            client = Minio(
                settings.minio_endpoint,  # host:port（如 localhost:9000）
                access_key=settings.minio_access_key,  # 访问密钥
                secret_key=settings.minio_secret_key,  # 密钥
                secure=settings.minio_secure,  # 是否 HTTPS（本地 false）
            )
            # 探测连通性：列出桶名（会真实访问一次 MinIO）
            client.list_buckets()
        except Exception as exc:  # 连接超时/认证失败等
            raise StorageUnavailable(f"MinIO 连接失败: {exc}") from exc

        self._client = client  # 缓存客户端
        self._connected = True
        return client

    def ensure_bucket(self, bucket: str | None = None) -> None:
        """确保指定桶存在（不存在则创建）。

        :param bucket: 桶名，默认取 settings.minio_input_bucket
        :raises StorageUnavailable: MinIO 不可用
        """
        client = self._get_client()
        bucket = bucket or settings.minio_input_bucket
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

    # ------------------------------------------------------------------
    # 上传 / 下载
    # ------------------------------------------------------------------
    def upload_bytes(
        self, data: bytes, bucket: str | None = None, key: str = ""
    ) -> str:
        """上传字节内容到 MinIO。

        :param data: 文件字节内容
        :param bucket: 桶名，默认输入桶
        :param key: 对象 Key（如 docagent-input/2026/08/03/{task_id}/xxx.docx）
        :return: 对象 Key
        :raises StorageUnavailable: MinIO 不可用
        """
        client = self._get_client()
        bucket = bucket or settings.minio_input_bucket
        self.ensure_bucket(bucket)
        client.put_object(
            bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        return key

    def upload_file(
        self, file_path: str, bucket: str | None = None, key: str = ""
    ) -> str:
        """上传本地文件到 MinIO。

        :param file_path: 本地文件路径
        :param bucket: 桶名，默认输出桶
        :param key: 对象 Key
        :return: 对象 Key
        :raises StorageUnavailable: MinIO 不可用
        """
        client = self._get_client()
        bucket = bucket or settings.minio_output_bucket
        self.ensure_bucket(bucket)
        client.fput_object(bucket, key, file_path)
        return key

    def download_file(
        self, key: str, bucket: str | None = None, local_path: str = ""
    ) -> None:
        """从 MinIO 下载对象到本地文件。

        :param key: 对象 Key
        :param bucket: 桶名，默认输入桶
        :param local_path: 本地目标路径
        :raises StorageUnavailable: MinIO 不可用
        """
        client = self._get_client()
        bucket = bucket or settings.minio_input_bucket
        client.fget_object(bucket, key, local_path)

    # ------------------------------------------------------------------
    # 预签名 URL / 删除
    # ------------------------------------------------------------------
    def presign_url(
        self, key: str, bucket: str | None = None, expires_seconds: int = 300
    ) -> str:
        """生成限时下载链接（默认 5 分钟，防防盗链）。

        :param key: 对象 Key
        :param bucket: 桶名，默认输出桶
        :param expires_seconds: 有效期（秒），默认 300
        :return: 预签名 URL
        :raises StorageUnavailable: MinIO 不可用
        """
        client = self._get_client()
        bucket = bucket or settings.minio_output_bucket
        return client.presigned_get_object(bucket, key, expires=expires_seconds)

    def delete_object(self, key: str, bucket: str | None = None) -> None:
        """删除指定对象（过期清理用）。

        :param key: 对象 Key
        :param bucket: 桶名，默认输入桶
        :raises StorageUnavailable: MinIO 不可用
        """
        client = self._get_client()
        bucket = bucket or settings.minio_input_bucket
        client.remove_object(bucket, key)


# 模块级单例：各节点直接 `from app.services.storage import storage` 使用
storage = MinioStorage()
