"""Atlas Trading Agent — CNINFO 公告快照采集器 (v2: Production Ready)

每日运行一次，从巨潮资讯网获取最新公告数据，
写入 historical.db 的 announcement_snapshot 表。

采集类型:
  - performance_forecast  业绩预告
  - performance_report    业绩快报
  - major_contract        重大合同/中标
  - buyback               回购/增持

v2 改进:
  - 自动分页（pageNum 循环直到最后一页）
  - 按月日期切片（避免单次查询数据量过大）
  - 断点续传（记录已完成的月份+关键词，中断后可恢复）
  - 保持 INSERT OR IGNORE 去重机制
  - 保持 available_time 逻辑不变

约束:
  - 不可重复写入相同公告（UNIQUE(code, publish_time, announce_type)）
  - 采集结果记录到 collection_tracking 表
  - 扫描阶段只读 snapshot，不访问网络
"""

import json
import time
from datetime import date, datetime, timedelta
from typing import Optional

from data.snapshot_schema import get_conn, SNAPSHOT_VERSION
from data.snapshot_query import query_announcements_as_of
from utils.logger import logger

# ── 默认时间范围 ──
_DEFAULT_LOOKBACK_DAYS = 7          # 每次增量采集过去 7 天
_PAGE_SIZE = 50                     # 每页记录数（CNINFO API 上限约 50）
_MONTHLY_SLICE = True               # 按月切片采集
_PAGE_REQUEST_INTERVAL = 0.5        # 页间请求间隔（秒）

# ── 关键词→announce_type 映射 ──
_KEYWORD_MAP = {
    "重大合同": "major_contract",
    "中标": "major_contract",
    "回购": "buyback",
    "增持": "buyback",
}

# ── 采集顺序（需要回填的关键词列表） ──
_COLLECTION_KEYWORDS = [
    ("业绩预告", "performance_forecast"),
    ("业绩快报", "performance_report"),
    ("重大合同", "major_contract"),
    ("中标", "major_contract"),
    ("回购", "buyback"),
    ("增持", "buyback"),
]

# ── 断点续传 tracker name ──
_TRACKER_NAME = "cninfo_announcement"


def _ts_to_iso(ts_ms: int) -> str:
    """CNINFO 毫秒时间戳 → ISO datetime"""
    if not ts_ms:
        return ""
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def _ts_to_date(ts_ms: int) -> str:
    """CNINFO 毫秒时间戳 → ISO date"""
    if not ts_ms:
        return ""
    return date.fromtimestamp(ts_ms / 1000).isoformat()


def _calc_available_time(publish_time_str: str) -> str:
    """根据公开时间计算可用时间。

    规则:
      - 交易时段 (09:30-15:00 CST) 发布: 立即可用 (available_time = publish_time)
      - 非交易时段发布（盘后/盘前/非交易日）: 推到下一交易日开盘 (date + 1 day)

    Args:
        publish_time_str: ISO datetime 如 "2026-04-30 15:30:00"
    Returns:
        ISO date 或 datetime
    """
    if not publish_time_str:
        return date.today().isoformat()

    try:
        dt = datetime.strptime(publish_time_str.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return publish_time_str[:10]

    hour_min = dt.hour * 100 + dt.minute  # e.g. 0930, 1500

    # A 股交易时段: 09:30 - 15:00
    TRADING_START = 930    # 09:30
    TRADING_END = 1500     # 15:00

    if TRADING_START <= hour_min < TRADING_END:
        # 盘中发布 → 立即可用
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        # 非交易时段 → 推到下一交易日
        next_day = dt.date() + timedelta(days=1)
        return next_day.isoformat()


def _clean_title(raw: str) -> str:
    """清除 HTML 标签"""
    return raw.replace("<em>", "").replace("</em>", "")


def _split_into_months(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """将日期范围按月切割，返回 [(month_start, month_end), ...] 列表。

    例如: 2024-01-15 ~ 2024-03-10 →
          [("2024-01-15", "2024-01-31"), ("2024-02-01", "2024-02-29"), ("2024-03-01", "2024-03-10")]
    """
    from calendar import monthrange
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    slices = []

    cursor = start
    while cursor <= end:
        # 当月最后一天
        _, last_day = monthrange(cursor.year, cursor.month)
        month_end = date(cursor.year, cursor.month, last_day)
        slice_end = min(month_end, end)
        slices.append((cursor.isoformat(), slice_end.isoformat()))
        # 下个月第一天
        if slice_end.month == 12:
            cursor = date(slice_end.year + 1, 1, 1)
        else:
            cursor = date(slice_end.year, slice_end.month + 1, 1)

    return slices


# ══════════════════════════════════════════════════════════════
# 公告采集器
# ══════════════════════════════════════════════════════════════

class CNInfoSnapshotCollector:
    """巨潮公告 → announcement_snapshot 采集器"""

    def __init__(self):
        self.conn = get_conn()
        self.stats = {
            "stocks": set(),
            "inserted": 0,
            "skipped_duplicates": 0,
            "failures": 0,
            "detail": {},
        }

    # ── 主入口 ──

    def collect_all(self, start_date: Optional[str] = None,
                    end_date: Optional[str] = None) -> dict:
        """全量采集所有公告类型。

        参数:
            start_date: YYYY-MM-DD, 默认7天前
            end_date: YYYY-MM-DD, 默认今天

        行为:
          - 如果日期范围 > 31 天，自动按月度切片采集
          - 每个切片内，6 个关键词分别搜索，自动分页
          - 支持断点续传：中断后重跑会自动跳过已完成的切片

        返回:
            {"stocks": N, "inserted": N, "skipped_duplicates": N,
             "failures": N, "detail": {type: N, ...}}
        """
        if not end_date:
            end_date = date.today().isoformat()
        if not start_date:
            start_date = (date.today() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)).isoformat()

        logger.info(f"CNINFO 快照采集: {start_date} ~ {end_date}")

        # 1) 按月切片
        months = _split_into_months(start_date, end_date)
        logger.info(f"  月度切片: {len(months)} 个 ({months[0][0]} ~ {months[-1][1]})")

        # 2) 加载断点续传状态
        resume_state = self._load_resume_state()

        # 3) 逐月采集
        for ym_start, ym_end in months:
            month_key = f"{ym_start[:7]}"  # "2024-01"

            # 断点续传：检查是否已完成此月
            if resume_state and self._is_month_done(resume_state, month_key):
                logger.info(f"  跳过已完成月份: {month_key}")
                # 仍然统计该月已有数据量（用于汇总）
                continue

            logger.info(f"  ── 采集月份: {month_key} ({ym_start} ~ {ym_end}) ──")

            # 逐关键词采集
            for keyword, announce_type in _COLLECTION_KEYWORDS:
                # 断点续传：检查此月此关键词是否已完成
                kw_key = f"{month_key}/{keyword}"
                if resume_state and kw_key in resume_state.get("done", []):
                    continue

                self._collect_keyword_paginated(keyword, announce_type,
                                                 ym_start, ym_end)

                # 记录此关键词完成
                self._update_resume_state(month_key, keyword)

            # 记录此月完成
            self._mark_month_done(month_key)

        # 4) 记录采集元数据
        self._record_tracking(start_date, end_date)

        result = {
            "stocks": len(self.stats["stocks"]),
            "inserted": self.stats["inserted"],
            "skipped_duplicates": self.stats["skipped_duplicates"],
            "failures": self.stats["failures"],
            "detail": self.stats["detail"],
        }
        logger.info(f"采集完成: {result}")
        return result

    # ── 带分页的通用采集 ──

    def _collect_keyword_paginated(self, keyword: str, announce_type: str,
                                    start_date: str, end_date: str):
        """带自动分页的单个关键词采集。

        自动循环 pageNum 直到捕获全部页面。
        """
        from data.cninfo_fetcher import _fulltext_search

        page = 1
        total_pages = 0  # 0 表示未知，第一页响应后会更新
        count = 0
        retries = 0

        while True:
            resp = _fulltext_search(
                keyword, page=page, page_size=_PAGE_SIZE,
                start_date=start_date, end_date=end_date,
            )

            if resp is None:
                # 网络失败，重试
                retries += 1
                if retries >= 3:
                    logger.warning(f"[{keyword}] 连续失败3次，跳过该关键词")
                    self.stats["failures"] += 1
                    break
                wait = 2 ** retries  # 指数退避: 2s, 4s, 8s
                logger.warning(f"[{keyword}] 第{page}页请求失败，{wait}s后重试")
                time.sleep(wait)
                continue

            retries = 0  # 成功后重置重试计数

            items = resp.get("announcements", [])
            if not items:
                break  # 无更多数据

            total_pages = resp.get("totalpages", 0) or 1

            # 处理本页公告
            for item in items:
                row = self._build_row(item, keyword, announce_type)
                if row and self._insert_one(row):
                    count += 1
                    self.stats["stocks"].add(row[0])

            # 判断是否还有下一页
            if page >= total_pages:
                break

            page += 1
            time.sleep(_PAGE_REQUEST_INTERVAL)

        self.stats["detail"][keyword] = self.stats["detail"].get(keyword, 0) + count
        if count:
            logger.info(f"  [{keyword}] {start_date}~{end_date}: 采集 {count} 条 ({page}/{total_pages}页)")

    # ── 行构建 ──

    def _build_row(self, item: dict, keyword: str,
                   announce_type: str) -> Optional[tuple]:
        """根据关键词类型构建数据库行。

        参数:
            item: CNINFO API 返回的公告条目
            keyword: 搜索关键词
            announce_type: 公告类型

        返回:
            tuple 或 None（时间戳无效时）
        """
        ts = item.get("announcementTime", 0)
        pt = _ts_to_iso(ts)
        if not pt:
            return None

        title = _clean_title(item.get("announcementTitle", ""))
        kw = keyword if keyword not in ("业绩预告", "业绩快报") else ""

        if announce_type == "performance_forecast":
            from data.cninfo_fetcher import _parse_forecast_from_title
            parsed = _parse_forecast_from_title(title)
            return (
                item.get("secCode", ""),
                item.get("secName", ""),
                pt,
                _calc_available_time(pt),
                announce_type,
                parsed.get("forecast_type", "业绩预告"),
                "业绩预告",
                parsed.get("net_profit_lower"),
                parsed.get("net_profit_upper"),
                parsed.get("change_pct_lower"),
                parsed.get("change_pct_upper"),
                title,
                kw,
            )
        elif announce_type == "performance_report":
            return (
                item.get("secCode", ""),
                item.get("secName", ""),
                pt,
                _calc_available_time(pt),
                announce_type,
                "业绩快报",
                "业绩快报",
                None, None, None, None,
                title,
                kw,
            )
        else:
            # major_contract / buyback
            kw = keyword  # 使用原始搜索关键词
            return (
                item.get("secCode", ""),
                item.get("secName", ""),
                pt,
                _calc_available_time(pt),
                announce_type,
                "", "",
                None, None, None, None,
                title,
                kw,
            )

    # ── 写入 ──

    def _insert_one(self, row: tuple) -> bool:
        """写入单条公告。返回 True=新增, False=重复跳过"""
        try:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO announcement_snapshot "
                "(code, name, publish_time, available_time, announce_type, "
                "report_type, forecast_type, "
                "net_profit_lower, net_profit_upper, "
                "change_pct_lower, change_pct_upper, "
                "title, keyword, "
                "source, snapshot_version) "
                "VALUES (?,?,?,?,?, ?,?, ?,?, ?,?, ?,?, ?,?)",
                row + ("cninfo", SNAPSHOT_VERSION)
            )
            if cur.rowcount and cur.rowcount > 0:
                self.stats["inserted"] += 1
                self.conn.commit()
                return True
            else:
                self.stats["skipped_duplicates"] += 1
                return False
        except Exception as e:
            logger.warning(f"写入公告失败: {e} [{row[0]} {row[2][:19]}]")
            self.stats["failures"] += 1
            return False

    # ── 断点续传状态管理 ──

    def _load_resume_state(self) -> Optional[dict]:
        """从 collection_tracking 加载断点续传状态"""
        try:
            cur = self.conn.execute(
                "SELECT stats_json FROM collection_tracking "
                "WHERE collector_name = ? ORDER BY last_run_at DESC LIMIT 1",
                (_TRACKER_NAME,)
            )
            row = cur.fetchone()
            if row:
                state = json.loads(row[0])
                if "resume" in state:
                    return state["resume"]
        except Exception:
            pass
        return None

    def _is_month_done(self, state: dict, month_key: str) -> bool:
        """检查某个月份是否已完成"""
        return month_key in state.get("months_done", [])

    def _update_resume_state(self, month_key: str, keyword: str):
        """更新本月的关键词完成状态到 collection_tracking"""
        kw_key = f"{month_key}/{keyword}"
        try:
            cur = self.conn.execute(
                "SELECT stats_json FROM collection_tracking "
                "WHERE collector_name = ? ORDER BY last_run_at DESC LIMIT 1",
                (_TRACKER_NAME,)
            )
            row = cur.fetchone()
            if row:
                state = json.loads(row[0])
            else:
                state = {}

            resume = state.get("resume", {})
            done = resume.get("done", [])
            if kw_key not in done:
                done.append(kw_key)
            resume["done"] = done
            state["resume"] = resume

            self.conn.execute(
                "INSERT OR REPLACE INTO collection_tracking "
                "(collector_name, last_run_at, last_success_at, status, stats_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    _TRACKER_NAME,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    None,
                    "in_progress",
                    json.dumps(state, ensure_ascii=False),
                )
            )
            self.conn.commit()
        except Exception as e:
            logger.warning(f"更新续传状态失败: {e}")

    def _mark_month_done(self, month_key: str):
        """标记某个月份为已完成"""
        try:
            cur = self.conn.execute(
                "SELECT stats_json FROM collection_tracking "
                "WHERE collector_name = ? ORDER BY last_run_at DESC LIMIT 1",
                (_TRACKER_NAME,)
            )
            row = cur.fetchone()
            if row:
                state = json.loads(row[0])
            else:
                state = {}

            resume = state.get("resume", {})
            months_done = resume.get("months_done", [])
            if month_key not in months_done:
                months_done.append(month_key)
            resume["months_done"] = months_done
            state["resume"] = resume

            self.conn.execute(
                "INSERT OR REPLACE INTO collection_tracking "
                "(collector_name, last_run_at, last_success_at, status, stats_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    _TRACKER_NAME,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    None,
                    "in_progress",
                    json.dumps(state, ensure_ascii=False),
                )
            )
            self.conn.commit()
        except Exception as e:
            logger.warning(f"标记月份完成失败: {e}")

    # ── 采集元数据 ──

    def _record_tracking(self, start_date: str, end_date: str):
        """记录本次采集结果（最终状态）"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO collection_tracking "
                "(collector_name, last_run_at, last_success_at, status, stats_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    _TRACKER_NAME,
                    now,
                    now if self.stats["failures"] == 0 else None,
                    "ok" if self.stats["failures"] == 0 else "partial",
                    json.dumps({
                        "start_date": start_date,
                        "end_date": end_date,
                        "stocks": len(self.stats["stocks"]),
                        "inserted": self.stats["inserted"],
                        "skipped": self.stats["skipped_duplicates"],
                        "failures": self.stats["failures"],
                        "detail": self.stats["detail"],
                    }, ensure_ascii=False),
                )
            )
            self.conn.commit()
        except Exception as e:
            logger.warning(f"记录采集元数据失败: {e}")


# ══════════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════════

def run_collector(start_date: Optional[str] = None,
                  end_date: Optional[str] = None) -> dict:
    """便捷入口 — 全量回填或增量更新"""
    collector = CNInfoSnapshotCollector()
    return collector.collect_all(start_date, end_date)


def run_incremental(days: int = _DEFAULT_LOOKBACK_DAYS) -> dict:
    """增量更新 — 采集最近 N 天的公告"""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    return run_collector(start, end)


def get_last_collection_time() -> Optional[str]:
    """获取最后一次成功采集时间"""
    conn = get_conn()
    cur = conn.execute(
        "SELECT last_success_at FROM collection_tracking "
        "WHERE collector_name = ? "
        "AND status = 'ok' ORDER BY last_run_at DESC LIMIT 1",
        (_TRACKER_NAME,)
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_today_collection_stats() -> dict:
    """获取今日采集统计"""
    today = date.today().isoformat()
    conn = get_conn()
    cur = conn.execute(
        "SELECT stats_json FROM collection_tracking "
        "WHERE collector_name = ? "
        "AND date(last_run_at) = ? "
        "ORDER BY last_run_at DESC LIMIT 1",
        (_TRACKER_NAME, today)
    )
    row = cur.fetchone()
    if row:
        return json.loads(row[0])
    return {}


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    print(f"CNINFO 公告采集: {start} ~ {end}")
    result = run_collector(start, end)
    print(f"\n结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
