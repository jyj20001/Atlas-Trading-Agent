"""
Buy Stop V3 — 通用工具函数
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR


# ── 简单文件缓存 ──

_cache_dir = DATA_DIR / ".cache"
_cache_dir.mkdir(parents=True, exist_ok=True)


def _cache_key(prefix: str, *args) -> str:
    raw = f"{prefix}:{':'.join(str(a) for a in args)}"
    return hashlib.md5(raw.encode()).hexdigest()


def cache_get(prefix: str, *args, ttl_seconds: int = 3600) -> Any:
    """读取缓存，过期返回 None"""
    key = _cache_key(prefix, *args)
    path = _cache_dir / f"{key}.json"
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl_seconds:
        path.unlink(missing_ok=True)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cache_set(prefix: str, *args, data: Any) -> None:
    """写入缓存"""
    key = _cache_key(prefix, *args)
    path = _cache_dir / f"{key}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")


# ── 市值分类 ──

def get_market_cap_category(market_cap: float) -> str:
    """根据流通市值(元)分类：large_cap / mid_cap / small_cap"""
    if market_cap >= 500e8:
        return "large_cap"
    elif market_cap >= 100e8:
        return "mid_cap"
    else:
        return "small_cap"


# ── 数值格式化 ──

def format_wan(val: float) -> str:
    """格式化万元"""
    if abs(val) >= 1e4:
        return f"{val / 1e4:.2f}亿"
    return f"{val:.2f}万"


def fmt_pct(val: float) -> str:
    """带符号百分数"""
    return f"{val:+.2f}%"


# ── 日期工具 ──

# (already handled inline with date.today().isoformat())
