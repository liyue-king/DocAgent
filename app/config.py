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
from pathlib import Path  # 项目根目录定位（.env 固定读取路径，与启动 CWD 无关）
from urllib.parse import (
    quote_plus,  # URL 编码：转义连接串中的特殊字符（如密码含 @ : / 等）
)

from pydantic_settings import (  # pydantic-settings 的两个核心类
    BaseSettings,
    SettingsConfigDict,
)

# 项目根目录（D:\work\DocAgent）：.env 固定从根目录读取，避免启动目录不同导致配置漂移
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """全局配置类：继承 BaseSettings，字段名即 .env 中的键名（自动映射）。"""

    # 配置模型：指定读取 .env 文件、UTF-8 编码、忽略未声明的多余环境变量
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------- MySQL ----------------
    mysql_host: str = "localhost"  # MySQL 主机地址（Docker 容器映射到宿主机）
    mysql_port: int = 3307  # 端口：Docker 容器映射到宿主机 3307（非默认 3306）
    mysql_user: str = "root"  # 连接用户名
    mysql_password: str = "docagent123"  # 连接密码（与 docker-compose.yml 一致）
    mysql_database: str = "docagent"  # 业务库名

    # ---------------- Redis ----------------
    redis_url: str = "redis://localhost:6379/0"  # db=0：Celery Broker（任务队列）
    redis_cache_url: str = (
        "redis://localhost:6379/2"  # db=2：应用级缓存（任务进度/状态/日志）
    )
    redis_snapshot_ttl_seconds: int = 3600  # 任务快照 TTL
    redis_logs_max: int = 20  # Redis 最近日志条数
    redis_ratelimit_ttl_seconds: int = 60  # IP 限流窗口
    redis_connect_timeout_seconds: int = 2  # Redis 连接超时
    redis_socket_timeout_seconds: int = 2  # Redis 读写超时

    # ---------------- MinIO（对象存储） ----------------
    minio_endpoint: str = "localhost:9000"  # MinIO API 地址（9000 为 API 端口）
    minio_access_key: str = (
        "docagent"  # 访问密钥 ID（与 compose 中 MINIO_ROOT_USER 一致）
    )
    minio_secret_key: str = "docagent123"  # 访问密钥密码
    minio_secure: bool = False  # 是否走 HTTPS（本地 http）
    minio_input_bucket: str = "docagent-input"  # 输入桶：存用户上传的原始 docx
    minio_output_bucket: str = "docagent-output"  # 输出桶：存处理后的 docx
    minio_knowledge_bucket: str = "docagent-knowledge"  # 知识库桶：存知识文档原文
    minio_presign_expires_seconds: int = 300  # 预签名下载 URL 有效期
    minio_connect_timeout_seconds: int = 5  # MinIO 连接超时
    minio_read_timeout_seconds: int = 5  # MinIO 读超时
    minio_connect_retries: int = 0  # MinIO 连接重试次数

    # ---------------- ChromaDB（向量库） ----------------
    chroma_host: str = "localhost"  # ChromaDB 主机
    chroma_port: int = 8002  # ChromaDB HTTP 端口（8002 避免与本机 8000 冲突；容器内由 compose 覆盖为 8000）
    chroma_health_timeout_seconds: int = 2  # Chroma 健康检查超时

    # ---------------- LLM ----------------
    llm_provider: str = "deepseek"  # 供应商：deepseek | openai | qwen
    deepseek_api_key: str = ""  # DeepSeek API Key（需在 .env 中填写）
    deepseek_base_url: str = "https://api.deepseek.com/v1"  # DeepSeek 接口地址
    openai_api_key: str = ""  # OpenAI API Key（备选）
    openai_base_url: str = "https://api.openai.com/v1"  # OpenAI 接口地址
    qwen_api_key: str = ""  # 千问(DashScope) API Key（sk-ws- 开头）
    qwen_base_url: str = (  # 千问 OpenAI 兼容接口地址
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    llm_model: str = "deepseek-chat"  # 默认模型：deepseek-chat | gpt-4o-mini | qwen3.7-max

    # ---------------- Celery（异步任务） ----------------
    celery_broker_url: str = "redis://localhost:6379/0"  # Broker：任务投递队列（db=0）
    celery_result_backend: str = "redis://localhost:6379/1"  # Result Backend（db=1）
    celery_soft_time_limit_seconds: int = 240  # 软超时
    celery_time_limit_seconds: int = 300  # 硬超时
    celery_beat_sweep_interval_seconds: int = 3600  # 过期清扫周期

    # ---------------- 登录认证（JWT） ----------------
    jwt_secret: str = "dev-secret-change-me"  # JWT 签名密钥（生产必须更换）
    jwt_algorithm: str = "HS256"  # JWT 签名算法
    jwt_expire_hours: int = 72  # token 有效期（小时）
    admin_emails: str = ""  # 管理员邮箱（逗号分隔；注册/登录/初始化时自动授予管理员）

    # ---------------- SMTP 邮箱验证码 ----------------
    smtp_host: str = "smtp.qq.com"  # SMTP 服务器（QQ 邮箱）
    smtp_port: int = 465  # SMTP 端口（465=SSL，587=TLS，25=普通）
    smtp_user: str = ""  # SMTP 账号（通常为邮箱地址）
    smtp_password: str = ""  # SMTP 授权码（QQ邮箱需在设置中开启SMTP获取）
    smtp_from: str = ""  # 发件人地址（默认与 smtp_user 同）
    email_code_ttl_seconds: int = 300  # 验证码有效期（秒）
    email_code_cooldown_seconds: int = 60  # 发送冷却时间（秒）
    email_code_max_attempts: int = 5  # 验证最大出错次数（超限需重发）

    # ---------------- 支付（支付宝沙箱） ----------------
    alipay_app_id: str = ""  # 支付宝应用应用号（沙箱 9021000165600064）
    alipay_private_key_path: str = "keys/app_private_key.pem"  # 应用私钥（PKCS8 PEM）
    alipay_public_key_path: str = "keys/alipay_public_key.pem"  # 支付宝公钥（PEM）
    alipay_gateway_url: str = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"  # 沙箱网关
    alipay_notify_url: str = "http://localhost:8001/api/v1/pay/notify"  # 同步回调地址
    alipay_return_url: str = "http://localhost:5173/pricing"  # 支付跳转（本项目）前端页面
    alipay_user_id: str = "2088722102597409"  # 沙箱测试购买者账号ID
    alipay_query_timeout_seconds: int = 5  # 订单查询超时

    # ---------------- MinerU 文档解析（知识库上传，可选） ----------------
    mineru_api_key: str = ""  # MinerU token（未配置时知识库上传走本地正则提取）
    mineru_base_url: str = "https://mineru.net/api/v4"  # MinerU API 基址（含 /api/v4）
    mineru_timeout_seconds: int = 120  # 解析任务轮询总超时（秒）

    # ---------------- LangGraph Checkpointer（断点持久化） ----------------
    checkpoint_db_path: str = "checkpoints/checkpoint.db"  # SQLite checkpoint 文件（容器内挂 /app/checkpoints）

    # ---------------- 应用参数 ----------------
    max_file_size_mb: int = 20  # 上传文件大小上限（MB）
    task_expire_hours: int = 24  # 任务/文件生命周期（小时后自动过期删除）
    max_retry_count: int = 3  # Validator 校验失败最大重试次数
    api_rate_limit: int = 10  # IP 限流：每分钟允许的请求数
    local_output_dir: str = "data/local_outputs"  # MinIO 失败时输出文件的本地稳定目录
    cors_allow_origins: str = "*"  # CORS 允许来源（逗号分隔或 *）
    api_client_timeout_seconds: int = 30  # API e2e 客户端超时
    api_base_url: str = "http://localhost:8001"  # API 默认基址
    api_port: int = 8001  # 网关默认端口（避开 Chroma 的 8000）

    @property
    def mysql_dsn(self) -> str:
        """生成 SQLAlchemy 连接串（PyMySQL 驱动 + utf8mb4 字符集）。"""
        # 用户名/密码做 URL 编码（quote_plus），防止特殊字符破坏连接串
        # 拼接：mysql+pymysql://用户:密码@主机:端口/库名?charset=utf8mb4
        return (
            f"mysql+pymysql://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    @property
    def local_output_dir_abs(self) -> str:
        """本地输出稳定目录的绝对路径（相对项目根目录解析）。"""
        return str(_PROJECT_ROOT / self.local_output_dir)


@lru_cache  # 缓存函数结果：整个进程生命周期内只解析一次 .env，提升性能
def get_settings() -> Settings:
    """单例获取配置（避免每次 import 重复解析 .env 文件）。"""
    return Settings()  # 实例化配置对象（此时自动读取 .env）


settings = (
    get_settings()
)  # 模块级单例：其它文件直接 `from app.config import settings` 使用
