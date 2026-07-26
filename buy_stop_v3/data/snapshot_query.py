"""Atlas Trading Agent — Historical Snapshot Query Interface

提供截至指定日期（signal_date）的历史数据查询接口。
所有查询使用 available_time <= signal_date 过滤，防止未来函数。

接口:
  query_announcements_as_of(signal_date, code=None) -> list[dict]
  query_fundamentals_as_of(signal_date, code=None) -> list[dict]
  query_sector_as_of(signal_date, index_code=None) -> list[dict]
  query_market_as_of(signal_date, index_code=None) -> list[dict]

约束:
  - 所有查询强制 WHERE available_time <= signal_date
  - 不允许无 signal_date 的全表扫描（通过 Row对象读取关闭）
  - 返回 dict 快照，只读不可修改
"""

from datetime import datetime
from typing import Optional
from data.snapshot_schema import get_conn


class SnapshotQueryError(Exception):
    """快照查询异常"""
    pass


def _validate_date(date_str: str) -> str:
    """验证日期格式，返回标准 YYYY-MM-DD"""
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        raise SnapshotQueryError(
            f"无效日期格式: '{date_str}'，应为 YYYY-MM-DD"
        )


def _resolve_time_filter(signal_date: str,
                          signal_datetime: Optional[str] = None) -> tuple[str, str]:
    """解析时间过滤条件。

    返回 (where_clause, param_value):
      - 提供 signal_datetime: 精确到秒, available_time <= signal_datetime
      - 仅 signal_date: 日期级, date(available_time) <= signal_date
    """
    sd = _validate_date(signal_date)
    if signal_datetime:
        # 验证 ISO datetime 格式
        try:
            datetime.strptime(signal_datetime.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise SnapshotQueryError(
                f"无效 datetime 格式: '{signal_datetime}'，应为 YYYY-MM-DD HH:MM:SS"
            )
        return "available_time <= ?", signal_datetime
    return "date(available_time) <= ?", sd


def _rows_to_dicts(rows, description) -> list[dict]:
    """将 sqlite3.Row 或 tuple 转为 dict 列表"""
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return rows
    columns = [d[0] for d in description]
    return [dict(zip(columns, row)) for row in rows]


# ── 公告快照查询 ──

def query_announcements_as_of(
    signal_date: str,
    code: Optional[str] = None,
    announce_type: Optional[str] = None,
    signal_datetime: Optional[str] = None,
) -> list[dict]:
    """返回截至 signal_date/signal_datetime 可见的公告快照。

    参数:
        signal_date: 信号日期 YYYY-MM-DD
        code: 可选，股票代码筛选
        announce_type: 可选，公告类型筛选
        signal_datetime: 可选，精确时间 YYYY-MM-DD HH:MM:SS
            当提供时，使用 available_time <= signal_datetime 过滤（同一天内精度）

    返回:
        list[dict]
    """
    time_where, time_param = _resolve_time_filter(signal_date, signal_datetime)
    conn = get_conn()
    where_parts = [time_where]
    params: list = [time_param]

    if code:
        where_parts.append("code = ?")
        params.append(code)
    if announce_type:
        where_parts.append("announce_type = ?")
        params.append(announce_type)

    sql = (
        "SELECT * FROM announcement_snapshot "
        f"WHERE {' AND '.join(where_parts)} "
        "ORDER BY available_time DESC"
    )
    cur = conn.execute(sql, params)
    return _rows_to_dicts(cur.fetchall(), cur.description)


# ── 基本面快照查询 ──

def query_fundamentals_as_of(
    signal_date: str,
    code: Optional[str] = None,
    fiscal_period: Optional[str] = None,
    signal_datetime: Optional[str] = None,
) -> list[dict]:
    """返回截至 signal_date/signal_datetime 可见的基本面快照。"""
    time_where, time_param = _resolve_time_filter(signal_date, signal_datetime)
    conn = get_conn()
    where_parts = [time_where]
    params: list = [time_param]

    if code:
        where_parts.append("code = ?")
        params.append(code)
    if fiscal_period:
        where_parts.append("fiscal_period = ?")
        params.append(fiscal_period)

    sql = (
        "SELECT * FROM fundamental_snapshot "
        f"WHERE {' AND '.join(where_parts)} "
        "ORDER BY available_time DESC"
    )
    cur = conn.execute(sql, params)
    return _rows_to_dicts(cur.fetchall(), cur.description)


# ── 板块快照查询 ──

def query_sector_as_of(
    signal_date: str,
    index_code: Optional[str] = None,
    sector_name: Optional[str] = None,
    signal_datetime: Optional[str] = None,
) -> list[dict]:
    """返回截至 signal_date/signal_datetime 可见的板块指数快照。"""
    time_where, time_param = _resolve_time_filter(signal_date, signal_datetime)
    conn = get_conn()
    where_parts = [time_where]
    params: list = [time_param]

    if index_code:
        where_parts.append("index_code = ?")
        params.append(index_code)
    if sector_name:
        where_parts.append("sector_name = ?")
        params.append(sector_name)

    sql = (
        "SELECT * FROM sector_snapshot "
        f"WHERE {' AND '.join(where_parts)} "
        "ORDER BY trade_date DESC"
    )
    cur = conn.execute(sql, params)
    return _rows_to_dicts(cur.fetchall(), cur.description)


# ── 市场快照查询 ──

def query_market_as_of(
    signal_date: str,
    index_code: Optional[str] = None,
    signal_datetime: Optional[str] = None,
) -> list[dict]:
    """返回截至 signal_date/signal_datetime 可见的市场快照（三大指数）。"""
    time_where, time_param = _resolve_time_filter(signal_date, signal_datetime)
    conn = get_conn()
    where_parts = [time_where]
    params: list = [time_param]

    if index_code:
        where_parts.append("index_code = ?")
        params.append(index_code)

    sql = (
        "SELECT * FROM market_snapshot "
        f"WHERE {' AND '.join(where_parts)} "
        "ORDER BY trade_date DESC"
    )
    cur = conn.execute(sql, params)
    return _rows_to_dicts(cur.fetchall(), cur.description)


# ── 批量查询（全量快照）──

def query_all_as_of(signal_date: str) -> dict[str, list[dict]]:
    """返回截至 signal_date 的所有 4 个快照维度。

    返回:
        {
            "announcements": [...],
            "fundamentals": [...],
            "sectors": [...],
            "markets": [...],
        }
    """
    return {
        "announcements": query_announcements_as_of(signal_date),
        "fundamentals": query_fundamentals_as_of(signal_date),
        "sectors": query_sector_as_of(signal_date),
        "markets": query_market_as_of(signal_date),
    }


# ── 快照统计 ──

def get_snapshot_stats() -> dict:
    """获取各快照表统计"""
    from data.snapshot_schema import TABLE_NAMES, get_table_count

    conn = get_conn()
    stats = {}
    for table in TABLE_NAMES:
        count = get_table_count(table)
        try:
            cur = conn.execute(
                f"SELECT COALESCE(MIN(date(available_time)), 'N/A'), "
                f"COALESCE(MAX(date(available_time)), 'N/A') "
                f"FROM {table}"
            )
            min_a, max_a = cur.fetchone()
        except Exception:
            min_a, max_a = "N/A", "N/A"
        stats[table] = {
            "count": count,
            "available_range": f"{min_a} ~ {max_a}",
        }
    return stats
