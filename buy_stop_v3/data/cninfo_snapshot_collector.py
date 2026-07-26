"""Atlas Trading Agent — CNINFO 公告快照采集器

每日运行一次，从巨潮资讯网获取最新公告数据，
写入 historical.db 的 announcement_snapshot 表。

采集类型:
  - performance_forecast  业绩预告
  - performance_report    业绩快报
  - major_contract        重大合同/中标
  - buyback               回购/增持

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
_DEFAULT_LOOKBACK_DAYS = 7  # 每次采集过去 7 天（增量）

# ── 关键词→announce_type 映射 ──
_KEYWORD_MAP = {
    "重大合同": "major_contract",
    "中标": "major_contract",
    "回购": "buyback",
    "增持": "buyback",
}


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
      - 交易时段 (09:30-15:00 CST) 发布: 立即可用
      - 非交易时段发布: 当收盘后才能用
    简化: 默认 publish_time = available_time
    """
    return publish_time_str


def _clean_title(raw: str) -> str:
    """清除 HTML 标签"""
    return raw.replace("<em>", "").replace("</em>", "")


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

        返回:
            {"stocks": N, "inserted": N, "skipped_duplicates": N,
             "failures": N, "detail": {type: N, ...}}
        """
        if not end_date:
            end_date = date.today().isoformat()
        if not start_date:
            start_date = (date.today() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)).isoformat()

        logger.info(f"CNINFO 快照采集: {start_date} ~ {end_date}")

        self._collect_forecasts(start_date, end_date)
        self._collect_reports(start_date, end_date)
        self._collect_keyword("重大合同", "major_contract", start_date, end_date)
        self._collect_keyword("中标", "major_contract", start_date, end_date)
        self._collect_keyword("回购", "buyback", start_date, end_date)
        self._collect_keyword("增持", "buyback", start_date, end_date)

        # 记录采集元数据
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

    # ── 业绩预告 ──

    def _collect_forecasts(self, start_date: str, end_date: str):
        """采集业绩预告"""
        from data.cninfo_fetcher import _fulltext_search
        items = _fulltext_search("业绩预告", page=1, page_size=50,
                                  start_date=start_date, end_date=end_date)
        if not items:
            logger.info("业绩预告: 无数据")
            return

        count = 0
        for item in items:
            ts = item.get("announcementTime", 0)
            pt = _ts_to_iso(ts)
            if not pt:
                continue
            title = _clean_title(item.get("announcementTitle", ""))

            from data.cninfo_fetcher import _parse_forecast_from_title
            parsed = _parse_forecast_from_title(title)

            row = (
                item.get("secCode", ""),
                item.get("secName", ""),
                pt,
                _calc_available_time(pt),
                "performance_forecast",
                parsed.get("forecast_type", "业绩预告"),
                "业绩预告",
                parsed.get("net_profit_lower"),
                parsed.get("net_profit_upper"),
                parsed.get("change_pct_lower"),
                parsed.get("change_pct_upper"),
                title,
                "",
            )
            if self._insert_one(row):
                count += 1
                self.stats["stocks"].add(row[0])

        self.stats["detail"]["forecasts"] = count
        logger.info(f"业绩预告: 采集 {count} 条")

    # ── 业绩快报 ──

    def _collect_reports(self, start_date: str, end_date: str):
        """采集业绩快报"""
        from data.cninfo_fetcher import _fulltext_search
        items = _fulltext_search("业绩快报", page=1, page_size=50,
                                  start_date=start_date, end_date=end_date)
        if not items:
            logger.info("业绩快报: 无数据")
            return

        count = 0
        for item in items:
            ts = item.get("announcementTime", 0)
            pt = _ts_to_iso(ts)
            if not pt:
                continue
            title = _clean_title(item.get("announcementTitle", ""))

            row = (
                item.get("secCode", ""),
                item.get("secName", ""),
                pt,
                _calc_available_time(pt),
                "performance_report",
                "业绩快报",
                "业绩快报",
                None, None, None, None,
                title,
                "",
            )
            if self._insert_one(row):
                count += 1
                self.stats["stocks"].add(row[0])

        self.stats["detail"]["reports"] = count
        logger.info(f"业绩快报: 采集 {count} 条")

    # ── 关键词公告（重大合同/中标/回购/增持）──

    def _collect_keyword(self, keyword: str, announce_type: str,
                         start_date: str, end_date: str):
        """采集指定关键词的公告"""
        from data.cninfo_fetcher import _fulltext_search
        items = _fulltext_search(keyword, page=1, page_size=50,
                                  start_date=start_date, end_date=end_date)
        if not items:
            logger.info(f"[{keyword}]: 无数据")
            return

        count = 0
        for item in items:
            ts = item.get("announcementTime", 0)
            pt = _ts_to_iso(ts)
            if not pt:
                continue
            title = _clean_title(item.get("announcementTitle", ""))

            row = (
                item.get("secCode", ""),
                item.get("secName", ""),
                pt,
                _calc_available_time(pt),
                announce_type,
                "",
                "",
                None, None, None, None,
                title,
                keyword,
            )
            if self._insert_one(row):
                count += 1
                self.stats["stocks"].add(row[0])

        self.stats["detail"][keyword] = count
        logger.info(f"[{keyword}]: 采集 {count} 条")

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

    # ── 采集元数据 ──

    def _record_tracking(self, start_date: str, end_date: str):
        """记录本次采集结果"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO collection_tracking "
                "(collector_name, last_run_at, last_success_at, status, stats_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "cninfo_announcement",
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
    """便捷入口"""
    collector = CNInfoSnapshotCollector()
    return collector.collect_all(start_date, end_date)


def get_last_collection_time() -> Optional[str]:
    """获取最后一次成功采集时间"""
    conn = get_conn()
    cur = conn.execute(
        "SELECT last_success_at FROM collection_tracking "
        "WHERE collector_name = 'cninfo_announcement' "
        "AND status = 'ok' ORDER BY last_run_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_today_collection_stats() -> dict:
    """获取今日采集统计"""
    today = date.today().isoformat()
    conn = get_conn()
    cur = conn.execute(
        "SELECT stats_json FROM collection_tracking "
        "WHERE collector_name = 'cninfo_announcement' "
        "AND date(last_run_at) = ? "
        "ORDER BY last_run_at DESC LIMIT 1",
        (today,)
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
