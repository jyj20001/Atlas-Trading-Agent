"""
Buy Stop V3 — HTTP 客户端（稳定版）

基于 curl 子进程执行 HTTP GET 请求，完全绕过 Python SSL 栈的兼容性问题。
支持东方财富 / 腾讯 / 新浪等多个数据源。

接口：
    get_json(url, params=None, retries=3, timeout=10) -> dict

异常：
    HttpError: 所有失败场景统一抛出
"""

import json
import random
import subprocess
import time
from typing import Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs, ParseResult

from utils.logger import logger


class HttpError(Exception):
    """HTTP 请求失败"""
    pass


def _build_url(base_url: str, params: Optional[dict] = None) -> str:
    """将 base_url 和 params 拼接为完整 URL"""
    if not params:
        return base_url

    parsed: ParseResult = urlparse(base_url)
    existing_params = parse_qs(parsed.query, keep_blank_values=True)
    for k, v in params.items():
        if isinstance(v, list):
            existing_params[k] = [str(x) for x in v]
        else:
            existing_params[k] = [str(v)]

    new_query = urlencode(existing_params, doseq=True)
    new_parsed = ParseResult(
        scheme=parsed.scheme, netloc=parsed.netloc,
        path=parsed.path, params=parsed.params,
        query=new_query, fragment=parsed.fragment,
    )
    return urlunparse(new_parsed)


def get_json(url: str, params: Optional[dict] = None,
             retries: int = 3, timeout: int = 10,
             _raw_text: bool = False) -> dict:
    """
    用 curl 执行 GET 请求，返回 JSON dict。

    参数：
        url: 基础 URL
        params: 查询参数字典
        retries: 重试次数（默认 3）
        timeout: 单次超时秒数（默认 10）
        _raw_text: 设为 True 则返回原始文本（用于非标准JSON响应）

    返回：
        dict 或 str（raw_text=True时）

    异常：
        HttpError
    """
    full_url = _build_url(url, params)
    last_error = ""

    for attempt in range(1, retries + 1):
        try:
            cmd = [
                "curl", "-s", "--max-time", str(timeout),
                "--noproxy", "*",
                "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", "Referer: https://quote.eastmoney.com/",
                full_url,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout + 5
            )

            if result.returncode != 0:
                last_error = f"curl exit {result.returncode}"
                stderr = result.stderr.strip()
                if stderr:
                    last_error += f": {stderr[:80]}"
                _sleep(attempt)
                continue

            raw = result.stdout.strip()
            if not raw:
                last_error = "empty response"
                _sleep(attempt)
                continue

            if _raw_text:
                return {"_raw": raw}

            # 有些API返回非标准JSON
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                if raw.startswith("[") and raw.endswith("]"):
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, list):
                            return {"_list": parsed}
                    except json.JSONDecodeError:
                        pass
                raise

        except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError) as e:
            last_error = f"{type(e).__name__}: {str(e)[:80]}"
            if attempt < retries:
                _sleep(attempt)

    raise HttpError(
        f"请求失败 ({retries}次) : {last_error} | {full_url[:60]}..."
    )


def get_text(url: str, params: Optional[dict] = None,
             retries: int = 3, timeout: int = 10) -> str:
    """获取原始文本响应（用于 CSV 或非JSON数据）"""
    full_url = _build_url(url, params)
    last_error = ""

    for attempt in range(1, retries + 1):
        try:
            cmd = [
                "curl", "-s", "--max-time", str(timeout),
                "--noproxy", "*",
                "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36",
                full_url,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout + 5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            last_error = f"exit {result.returncode}"
            _sleep(attempt)
        except (subprocess.TimeoutExpired, OSError) as e:
            last_error = f"{type(e).__name__}: {str(e)[:60]}"
            _sleep(attempt)

    raise HttpError(f"请求文本失败 ({retries}次) : {last_error}")


def _sleep(attempt: int) -> None:
    delay = 0.5 + random.random() * 0.8
    time.sleep(delay)
