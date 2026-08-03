"""
====================================================================
文件用途：应用配置中心（整个应用的唯一配置入口）
====================================================================
作用：
    从根目录 .env 文件读取全部运行参数（数据库 / 缓存 / 对象存储 /
    向量库 / LLM / 任务参数），并集中管理。
依赖：
    - pydantic-settings：把 .env 中的环境变量自动映射为类型化字段。
调用方：
    - app/db.py           -> settings.mysql_dsn（构造数据库连接串）
    - app/crud/tasks.py   -> settings.task_expire_hours（任务过期时间）
    - 后续 MinIO / ChromaDB / LLM / Celery 服务均从此处取配置
约定：
    - 字段名与 .env.example 一一对应（环境变量名大小写不敏感）。
    - 宿主机 MySQL 端口为 3307（3306 被本机 MySQL 占用，见 docker-compose.yml）。
====================================================================
"""

from functools import lru_cache  # 导入 lru_cache：实现“单例”配置对象，避免重复解析 .env
from urllib.parse import (
    quote_plus,  # URL 编码：转义连接串中的特殊字符（如密码含 @ : / 等）
)

from pydantic_settings import (  # pydantic-settings 的两个核心类
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    """全局配置类：继承 BaseSettings，字段名即 .env 中的键名（自动映射）。"""

    # 配置模型：指定读取 .env 文件、UTF-8 编码、忽略未声明的多余环境变量
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---------------- MySQL ----------------
    mysql_host: str = "localhost"       # MySQL 主机地址（Docker 容器映射到宿主机）
    mysql_port: int = 3307              # 端口：Docker 容器映射到宿主机 3307（非默认 3306）
    mysql_user: str = "root"            # 连接用户名
    mysql_password: str = "docagent123" # 连接密码（与 docker-compose.yml 一致）
    mysql_database: str = "docagent"    # 业务库名

    # ---------------- Redis ----------------
    redis_url: str = "redis://localhost:6379/0"       # db=0：Celery Broker（任务队列）
    redis_cache_url: str = "redis://localhost:6379/2" # db=2：应用级缓存（任务进度/状态/日志）

    # ---------------- MinIO（对象存储） ----------------
    minio_endpoint: str = "localhost:9000"  # MinIO API 地址（9000 为 API 端口）
    minio_access_key: str = "docagent"      # 访问密钥 ID（与 compose 中 MINIO_ROOT_USER 一致）
    minio_secret_key: str = "docagent123"   # 访问密钥密码
    minio_secure: bool = False              # 是否走 HTTPS（本地 http）
    minio_input_bucket: str = "docagent-input"   # 输入桶：存用户上传的原始 docx
    minio_output_bucket: str = "docagent-output" # 输出桶：存处理后的 docx

    # ---------------- ChromaDB（向量库） ----------------
    chroma_host: str = "localhost"  # ChromaDB 主机
    chroma_port: int = 8000         # ChromaDB HTTP 端口

    # ---------------- LLM ----------------
    llm_provider: str = "deepseek"  # 供应商：deepseek | openai
    deepseek_api_key: str = ""      # DeepSeek API Key（需在 .env 中填写）
    deepseek_base_url: str = "https://api.deepseek.com/v1"  # DeepSeek 接口地址
    openai_api_key: str = ""        # OpenAI API Key（备选）
    openai_base_url: str = "https://api.openai.com/v1"      # OpenAI 接口地址
    llm_model: str = "deepseek-chat"  # 默认模型：deepseek-chat | gpt-4o-mini

    # ---------------- Celery（异步任务） ----------------
    celery_broker_url: str = "redis://localhost:6379/0"  # Broker：任务投递队列（db=0）
    celery_result_backend: str = "redis://localhost:6379/1"  # Result Backend（db=1）

    # ---------------- 应用参数 ----------------
    max_file_size_mb: int = 20  # 上传文件大小上限（MB）
    task_expire_hours: int = 24 # 任务/文件生命周期（小时后自动过期删除）
    max_retry_count: int = 3    # Validator 校验失败最大重试次数
    api_rate_limit: int = 10    # IP 限流：每分钟允许的请求数

    @property
    def mysql_dsn(self) -> str:
        """生成 SQLAlchemy 连接串（PyMySQL 驱动 + utf8mb4 字符集）。"""
        # 用户名/密码做 URL 编码（quote_plus），防止特殊字符破坏连接串
        # 拼接：mysql+pymysql://用户:密码@主机:端口/库名?charset=utf8mb4
        return (
            f"mysql+pymysql://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )


@lru_cache  # 缓存函数结果：整个进程生命周期内只解析一次 .env，提升性能
def get_settings() -> Settings:
    """单例获取配置（避免每次 import 重复解析 .env 文件）。"""
    return Settings()  # 实例化配置对象（此时自动读取 .env）


settings = get_settings()  # 模块级单例：其它文件直接 `from app.config import settings` 使用
