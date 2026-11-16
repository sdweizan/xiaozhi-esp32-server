"""咪咕（中国移动）音乐授权查询客户端。

接口：POST {base_url}/lx-device-manager/cloud/json/miniprogram/migu/auth/queryBySn

签名规则：
    signature = SHA1(clientSecret + timestamp + paramStr)
    - POST 场景下 paramStr = **请求体 JSON 本身**，其中 KEY 必须按升序排列
    - 加密要求严格，因此实际发送的 body 必须与参与签名的 paramStr 字节级一致

返回：
    resultCode = 0 表示成功；data.phone 为手机号（密文，原样透传），
    data.authStatus 为 1（已授权）/ 0（未授权）。未授权时可能不含 data 字段。
"""

import json
import time
import hashlib
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Any

import aiohttp

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

DEFAULT_BASE_URL = "https://a2link.komect.com"
DEFAULT_PATH = "/lx-device-manager/cloud/json/miniprogram/migu/auth/queryBySn"

# 错误码（与服务端下行 music_play.state=error 的 code 保持一致）
ERR_PARAM = 1  # 参数错误（缺少 sn / keyword）
ERR_UNSUPPORTED = 2  # 设备未声明支持咪咕
ERR_TIMEOUT = 3  # 鉴权接口超时 / 网络异常
ERR_INTERNAL = 4  # 服务器内部错误 / 咪咕接口返回非成功码


class MiguAuthError(Exception):
    """咪咕鉴权接口异常（网络 / 超时 / 协议层）"""

    def __init__(self, message: str, code: int = ERR_INTERNAL):
        super().__init__(message)
        self.code = code


@dataclass
class MiguAuthResult:
    """鉴权查询结果"""

    auth_status: int  # 1 已授权 / 0 未授权
    phone: Optional[str] = None  # 手机号（密文，原样透传，不做解密）
    result_code: int = 0
    result_desc: str = ""

    @property
    def authorized(self) -> bool:
        return self.auth_status == 1


def build_param_str(body: Dict[str, Any]) -> str:
    """构造签名用的 paramStr：POST 为请求体本身，KEY 按升序排列。

    注意：这里同时用于签名与请求体发送，保证两者字节级一致。
    """
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_signature(client_secret: str, timestamp: str, param_str: str) -> str:
    """signature = SHA1(clientSecret + timestamp + paramStr)"""
    raw = f"{client_secret}{timestamp}{param_str}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


async def query_by_sn(
    sn: str,
    *,
    client_id: str,
    client_secret: str,
    product_code: str = "TEST",
    base_url: str = DEFAULT_BASE_URL,
    path: str = DEFAULT_PATH,
    timeout: float = 8.0,
) -> MiguAuthResult:
    """按设备 SN 查询咪咕授权信息。

    Args:
        sn: 设备序列号（由客户端上报，服务端原样使用）
        client_id / client_secret: 璇玑颁发的凭据
        product_code: 产品编码，对接期固定传 "TEST"
        base_url / path: 接口地址
        timeout: 请求超时（秒）

    Raises:
        MiguAuthError: 网络异常、超时、HTTP 非 200、resultCode != 0
    """
    if not sn:
        raise MiguAuthError("缺少设备 SN", code=ERR_PARAM)

    timestamp = str(int(time.time() * 1000))
    body = {"sn": sn, "productCode": product_code}
    param_str = build_param_str(body)
    signature = build_signature(client_secret, timestamp, param_str)
    url = base_url.rstrip("/") + path

    headers = {
        "clientId": client_id,
        "timestamp": timestamp,
        "signature": signature,
        "Content-Type": "application/json",
    }

    client_timeout = aiohttp.ClientTimeout(total=timeout)
    logger.bind(tag=TAG).info(
        f"[咪咕鉴权] ▶ 请求 url={url}\n"
        f"    └─ headers: clientId={client_id} timestamp={timestamp} signature={signature}\n"
        f"    └─ body: {param_str}"
    )
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(
                url, data=param_str.encode("utf-8"), headers=headers
            ) as resp:
                text = await resp.text()
                status = resp.status
    except asyncio.TimeoutError:
        logger.bind(tag=TAG).error(
            f"[咪咕鉴权] ✖ 超时 sn={sn} timeout={timeout}s url={url}"
        )
        raise MiguAuthError("咪咕鉴权接口超时", code=ERR_TIMEOUT)
    except aiohttp.ClientError as e:
        logger.bind(tag=TAG).error(f"[咪咕鉴权] ✖ 网络错误 sn={sn} err={e}")
        raise MiguAuthError(f"咪咕鉴权接口网络错误: {e}", code=ERR_TIMEOUT)

    logger.bind(tag=TAG).info(f"[咪咕鉴权] ◀ 返回 http={status} sn={sn} resp={text}")

    if status != 200:
        raise MiguAuthError(f"咪咕鉴权接口 HTTP {status}", code=ERR_INTERNAL)

    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise MiguAuthError("咪咕鉴权接口返回非 JSON", code=ERR_INTERNAL)

    if not isinstance(payload, dict):
        raise MiguAuthError("咪咕鉴权接口返回格式异常", code=ERR_INTERNAL)

    result_code = int(payload.get("resultCode", -1))
    result_desc = str(payload.get("resultCodeDesc", "") or "")
    if result_code != 0:
        message = (
            payload.get("resultCodeMessage")
            or result_desc
            or f"resultCode={result_code}"
        )
        logger.bind(tag=TAG).error(
            f"[咪咕鉴权] ✖ 业务失败 sn={sn} resultCode={result_code} msg={message}"
        )
        raise MiguAuthError(str(message), code=ERR_INTERNAL)

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    phone = data.get("phone")
    try:
        auth_status = int(data.get("authStatus", 0))
    except (TypeError, ValueError):
        auth_status = 0

    logger.bind(tag=TAG).info(
        f"[咪咕鉴权] ✔ 解析结果 sn={sn} authStatus={auth_status} "
        f"({'已授权' if auth_status == 1 else '未授权'}) "
        f"phone={'有(密文,长度%s)' % len(phone) if phone else '无'} "
        f"resultCode={result_code}"
    )

    return MiguAuthResult(
        auth_status=auth_status,
        phone=phone if phone else None,
        result_code=result_code,
        result_desc=result_desc,
    )
