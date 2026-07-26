"""Atlas Trading Agent — 富途 OpenD K线 Provider

使用富途 OpenAPI (futu-api) 通过本地 OpenD 进程获取全量历史 K 线。

前置条件:
  1. 安装 futu-api: pip install futu-api
  2. 启动 Futu OpenD（独立进程，默认端口 11111）
  3. 富途牛牛客户端已登录

接口:
  request_history_kline(code, start, end, ktype=K_DAY,
                        autype=qfq, max_count=1000, page_req_key=None)

分页:
  max_count=1000 最多返回 1000 根，page_req_key 用于翻页。
  设 max_count=None 可一次性返回全部（但可能耗时较长且内存大）。
"""

import logging
from typing import Optional

from .base import KLineProvider, KLineNormalized

logger = logging.getLogger(__name__)

# 复权类型映射
_ADJUST_MAP = {
    "qfq": "qfq",     # 前复权
    "hfq": "hfq",     # 后复权
    "none": None,     # 不复权
}


class FutuProvider(KLineProvider):
    """富途 OpenD K 线 Provider

    连接本地 OpenD 进程获取数据。
    OpenD 未运行时会优雅降级（返回空列表，不抛异常）。
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self._host = host
        self._port = port
        self._ctx = None

    @property
    def name(self) -> str:
        return "futu"

    @property
    def priority(self) -> int:
        return -1  # 最高优先级（优于 EastMoney=0）

    def fetch(self, code: str, *,
              start_date: Optional[str] = None,
              end_date: Optional[str] = None,
              adjust: str = "qfq",
              max_count: int = 2000) -> list[KLineNormalized]:
        """通过富途 OpenD 获取历史日 K 线"""
        ctx = self._get_context()
        if ctx is None:
            return []

        autype = _ADJUST_MAP.get(adjust, "qfq")

        # 构造股票代码
        futu_code = self._to_futu_code(code)
        if not futu_code:
            return []

        all_data = []
        page_key = None

        try:
            while True:
                ret, data, page_key = ctx.request_history_kline(
                    code=futu_code,
                    start=start_date,
                    end=end_date,
                    ktype="K_DAY",
                    autype=autype,
                    max_count=1000,
                    page_req_key=page_key,
                )

                if ret != 0:
                    logger.warning(f"Futu {code}: 获取失败 (ret={ret})")
                    break

                if data is None or data.empty:
                    break

                # 转换数据
                for _, row in data.iterrows():
                    try:
                        trade_date = str(row.get("time_key", ""))[:10]
                        if not trade_date:
                            continue
                        all_data.append(KLineNormalized(
                            code=code,
                            trade_date=trade_date,
                            open=float(row.get("open", 0)),
                            high=float(row.get("high", 0)),
                            low=float(row.get("low", 0)),
                            close=float(row.get("close", 0)),
                            volume=int(float(row.get("volume", 0))),
                            amount=float(row.get("turnover", 0)),
                            source="futu",
                            adjust_type=adjust,
                        ))
                    except (ValueError, TypeError):
                        continue

                # 没有更多分页
                if page_key is None:
                    break

                # 防无限循环
                if len(all_data) > 10000:
                    logger.warning(f"Futu {code}: 数据超过 10000 根，截断")
                    break

        except Exception as e:
            logger.warning(f"Futu {code}: 请求异常: {e}")
            if not all_data:
                return []
            # 已有部分数据，继续

        if not all_data:
            return []

        # 按日期去重 + 排序
        seen = set()
        unique = []
        for k in sorted(all_data, key=lambda x: x.trade_date):
            if k.trade_date not in seen:
                seen.add(k.trade_date)
                unique.append(k)

        return unique

    def _get_context(self):
        """获取或创建 OpenD 连接（快速失败，不阻塞）"""
        if self._ctx is not None:
            return self._ctx

        try:
            from futu import OpenQuoteContext
            self._ctx = OpenQuoteContext(
                host=self._host,
                port=self._port,
                is_async_connect=True,
            )
            return self._ctx
        except ImportError:
            logger.warning("futu-api 未安装: pip install futu-api")
            return None
        except Exception as e:
            logger.warning(f"Futu OpenD 连接异常: {type(e).__name__}: {e}")
            return None

    def close(self):
        """关闭 OpenD 连接"""
        if self._ctx:
            try:
                self._ctx.close()
            except Exception:
                pass
            self._ctx = None

    @staticmethod
    def _to_futu_code(code: str) -> Optional[str]:
        """A 股代码转富途格式

        富途格式: SH.600000 / SZ.000001 / BJ.430017
        """
        code = code.strip()
        if code.startswith(("6", "9")):
            return f"SH.{code}"
        elif code.startswith(("0", "3", "2")):
            return f"SZ.{code}"
        elif code.startswith(("4", "8")):
            return f"BJ.{code}"
        return None
