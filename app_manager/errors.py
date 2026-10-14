"""Readable operation errors; preserve command diagnostics for explicit inspection."""
import re
from urllib.parse import urlsplit


def connection_error(message):
    value = message.lower()
    return any(term in value for term in (
        "ssl connection failed", "certificate verify failed", "certificate verification failed",
        "tls connection", "failed to fetch", "temporary failure resolving", "could not resolve",
        "connection timed out", "connection reset", "connection refused", "network is unreachable"))


def friendly_error(message):
    value = message.lower()
    if any(term in value for term in ("certificate", "ssl connection failed", "tls connection")):
        return "软件源的安全连接验证失败，请稍后重试。"
    if "授权已取消" in message or "not authorized" in value or "authentication" in value:
        return "系统授权未完成，请重新检查并完成授权。"
    if "超时" in message or "timed out" in value or "timeout" in value:
        return "连接或操作超时，请稍后重试。"
    if any(term in value for term in ("could not get lock", "unable to acquire", "is another process using")):
        return "系统正在执行其他软件管理操作，请完成后重试。"
    if any(term in value for term in ("no_pubkey", "signatures couldn't be verified", "not signed", "signature verification")):
        return "软件源签名校验未通过，请检查软件源配置。"
    if connection_error(message):
        return "部分软件源暂时无法连接，请稍后重试。"
    if re.search(r"(?:^|\n)[EW]:|Traceback|\berror:|\bfailed\b|\bFailure\b|\bUnable\b|\bPermission denied\b", message, re.I) or (
            not re.search(r"[\u4e00-\u9fff]", message) and re.search(r"[A-Za-z]{4}", message)):
        return "操作未完成，请查看详情后重试。"
    return message


def diagnostic_text(message):
    # Repository URLs may contain credentials; details must not expose them.
    def redact(match):
        url = match.group(0)
        try:
            parsed = urlsplit(url)
            if parsed.username is not None or parsed.password is not None:
                return parsed._replace(netloc="[已隐藏凭据]@" + parsed.netloc.rsplit("@", 1)[-1]).geturl()
        except ValueError:
            return "[无效地址]"
        return url
    return re.sub(r"https?://[^\s]+", redact, message)
