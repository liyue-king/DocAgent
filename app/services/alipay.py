"""
====================================================================
文件用途：支付宝沙箱支付服务（RSA2 签名 / 下单 / 回调验签 / 查单）
====================================================================
作用：
    1. 套餐目录：pro（¥29/100 次）、team（¥99/500 次），与前端定价页对齐。
    2. 电脑网站支付 alipay.trade.page.pay：生成签名后的跳转 URL，
       前端 window.location 直达支付宝沙箱收银台。
    3. 异步通知验签 alipay.trade.page.pay 的 POST 回调（notify_url），
       通过支付宝公钥 RSA2 验签后由路由落库加积分。
    4. 主动查单 alipay.trade.query：前端跳回后轮询订单终态，
       不依赖异步通知的到达时间（双通道幂等）。
依赖：
    - cryptography（PEM 密钥加载 / PKCS1v15 + SHA256 签名）
    - httpx（POST 查单）
    - app.config.settings（沙箱网关/密钥路径/回调地址）
调用方：
    - app/api/pay.py（下单 / 通知 / 查单）
说明：
    - 密钥文件：keys/app_private_key.pem（应用私钥，PKCS8）、
      keys/alipay_public_key.pem（支付宝公钥，PEM）。
    - 签名串规范：所有参数按 key 升序拼接 k=v（原始值、不做 URL 编码），
      sign_type=RSA2 不参与签名，sign 字段不参与验签。
====================================================================
"""

from __future__ import annotations

import json  # biz_content 序列化
import logging  # 标准库日志
import os  # 路径判断
from datetime import datetime  # 支付宝 timestamp 格式
from pathlib import Path  # 项目根目录定位
from typing import Any  # 泛型类型
from urllib.parse import urlencode  # 拼接跳转 URL

from cryptography.hazmat.primitives import hashes, serialization  # 哈希与密钥序列化
from cryptography.hazmat.primitives.asymmetric import padding  # PKCS1v15 填充

from app.config import settings  # 沙箱配置

logger = logging.getLogger(__name__)  # 模块级日志器

# 项目根目录（D:\work\DocAgent）：services/ -> app/ -> 项目根
# keys/ 相对路径按根目录解析，与启动 CWD 无关
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------- 套餐目录（与前端 PricingView 对齐） ----------------
PLAN_CATALOG: dict[str, dict[str, Any]] = {
    "pro": {
        "name": "专业版",
        "price": "29.00",  # 元（两位小数，支付宝 total_amount 格式）
        "credits": 100,  # 到账额度（次）
        "desc": "每月 100 次处理",
    },
    "team": {
        "name": "团队版",
        "price": "99.00",
        "credits": 500,
        "desc": "每月 500 次处理",
    },
}


class AlipayError(Exception):
    """支付宝业务异常（密钥缺失/签名失败/接口异常）。"""

    def __init__(self, msg: str, code: int = 1204) -> None:
        super().__init__(msg)
        self.msg = msg
        self.code = code


def _load_private_key() -> Any:
    """加载应用私钥（PKCS8 PEM）。缺失/非法抛 AlipayError。"""
    path = settings.alipay_private_key_path
    if not os.path.isabs(path):
        path = str(_PROJECT_ROOT / path)
    try:
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)
    except FileNotFoundError as exc:
        raise AlipayError("支付宝应用私钥缺失，请配置 keys/app_private_key.pem", 1204) from exc
    except (ValueError, TypeError) as exc:
        raise AlipayError("支付宝应用私钥格式错误（需 PKCS8 PEM）", 1204) from exc


def _load_public_key() -> Any:
    """加载支付宝公钥（PEM）。缺失/非法抛 AlipayError。"""
    path = settings.alipay_public_key_path
    if not os.path.isabs(path):
        path = str(_PROJECT_ROOT / path)
    try:
        with open(path, "rb") as f:
            return serialization.load_pem_public_key(f.read())
    except FileNotFoundError as exc:
        raise AlipayError("支付宝公钥缺失，请配置 keys/alipay_public_key.pem", 1204) from exc
    except (ValueError, TypeError) as exc:
        raise AlipayError("支付宝公钥格式错误（需 PEM）", 1204) from exc


def _sign_str(params: dict[str, str]) -> str:
    """生成待签名串：key 升序拼接 k=v（原始值）。"""
    return "&".join(f"{k}={params[k]}" for k in sorted(params))


def _rsa2_sign(content: str) -> str:
    """RSA2（SHA256 + PKCS1v15）签名，返回 Base64。"""
    import base64

    private_key = _load_private_key()
    signature = private_key.sign(
        content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
    )
    return base64.b64encode(signature).decode("ascii")


def _rsa2_verify(content: str, signature: str) -> bool:
    """RSA2 验签，失败返回 False（不抛异常）。"""
    import base64

    try:
        public_key = _load_public_key()
        public_key.verify(
            base64.b64decode(signature),
            content.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception as exc:  # 密钥缺失/签名不符
        logger.warning("[alipay] 验签失败: %s", exc)
        return False


def build_page_pay_url(
    order_id: str, amount: str, subject: str, plan_name: str | None = None
) -> str:
    """构建电脑网站支付跳转 URL（alipay.trade.page.pay）。

    :param order_id: 商户订单号（out_trade_no，唯一）
    :param amount: 金额（元，两位小数，如 "29.00"）
    :param subject: 商品标题
    :param plan_name: 商品描述（可选）
    :return: 完整网关 URL（带签名参数），前端直接跳转
    :raises AlipayError: 密钥缺失或签名失败
    """
    if not settings.alipay_app_id:
        raise AlipayError("支付宝 APP_ID 未配置，请检查 .env", 1204)
    biz_content = json.dumps(
        {
            "out_trade_no": order_id,  # 商户订单号
            "product_code": "FAST_INSTANT_TRADE_PAY",  # 电脑网站支付产品码
            "total_amount": amount,  # 订单金额
            "subject": subject,  # 商品标题
            "body": plan_name or subject,  # 商品描述
            "timeout_express": "30m",  # 超时关单
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    params: dict[str, str] = {
        "app_id": settings.alipay_app_id,
        "method": "alipay.trade.page.pay",
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": settings.alipay_notify_url,  # 异步回调
        "return_url": settings.alipay_return_url,  # 同步跳回
        "biz_content": biz_content,
    }
    sign = _rsa2_sign(_sign_str(params))  # 签名（sign_type 不参与）
    params["sign"] = sign
    return f"{settings.alipay_gateway_url}?{urlencode(params)}"


def verify_notify(params: dict[str, str]) -> bool:
    """校验支付宝异步通知签名。

    :param params: POST 表单原始参数（sign/sign_type 不参与验签）
    :return: True=验签通过
    """
    sign = params.get("sign", "")
    if not sign:
        return False
    content = _sign_str({k: v for k, v in params.items() if k not in ("sign", "sign_type")})
    return _rsa2_verify(content, sign)


def query_order(order_id: str) -> dict[str, Any]:
    """主动查询订单状态（alipay.trade.query）。

    :param order_id: 商户订单号
    :return: 支付宝响应 JSON（含 trade_status / trade_no / total_amount）
    :raises AlipayError: 密钥缺失 / 网络失败 / 接口返回错误
    """
    if not settings.alipay_app_id:
        raise AlipayError("支付宝 APP_ID 未配置，请检查 .env", 1204)
    biz_content = json.dumps(
        {"out_trade_no": order_id}, ensure_ascii=False, separators=(",", ":")
    )
    params: dict[str, str] = {
        "app_id": settings.alipay_app_id,
        "method": "alipay.trade.query",
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "biz_content": biz_content,
    }
    sign = _rsa2_sign(_sign_str(params))
    params["sign"] = sign
    try:
        import httpx  # 延迟导入（仅查单用到）

        resp = httpx.post(
            settings.alipay_gateway_url,
            data=params,
            timeout=settings.alipay_query_timeout_seconds,
        )
        data = resp.json()
    except Exception as exc:  # 网络超时/响应非 JSON
        logger.warning("[alipay] 查单请求失败: %s", exc)
        raise AlipayError("支付宝订单查询失败，请稍后再试", 1204) from exc
    if data.get("alipay_trade_query_response", {}).get("code") != "10000":
        logger.warning("[alipay] 查单接口返回异常: %s", data)
        raise AlipayError("支付宝订单查询失败，请稍后再试", 1204)
    return data["alipay_trade_query_response"]


def is_trade_success(trade_status: str | None) -> bool:
    """终态判定：TRADE_SUCCESS / TRADE_FINISHED 视为支付成功。"""
    return trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED")
