"""Atlas Trading Agent — 基本面财务数据采集器

数据源: 东方财富数据中心 (datacenter-web.eastmoney.com)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
架构说明:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Atlas 的基本面数据层采用双数据源设计:

CNINFO (巨潮资讯)  ← 公告元数据
    ↓
    announcement_snapshot   — 业绩预告/快报/合同/回购
    （用于 FundamentalScorer 评分，来源: cninfo）

EastMoney (东方财富)  ← 结构化财务数据
    ↓
    fundamental_snapshot    — 营收/净利/ROE/毛利率
    （用于回测查询，来源: eastmoney，source 字段明确标记）

理由:
  CNINFO 是中国证监会指定信息披露平台，提供准确的公告时间和全文。
  但它不提供结构化的财务指标数据（营收、净利润、ROE 等数字）。
  东方财富数据中心提供结构化财务指标，数据源自上市公司公开财报。

  source 字段在每行数据中明确记录，绝不含混。

防未来函数:
  每条数据记录 announcement_date（公告日期），
  available_time = announcement_date + 1 天。
  回测查询必须使用 available_time <= signal_date 过滤。

字段映射:
  营业收入   → TOTALOPERATEREVE
  归母净利润 → PARENTNETPROFIT
  营收同比   → DJD_TOI_YOY (%)
  净利润同比 → PARENTNETPROFITTZ (%)
  ROE       → ROEJQ (%)
  毛利率    → XSMLL (%)
  净利率    → XSJLL (%)
  资产负债率 → ZCFZL (%)
  经营现金流 → NETCASH_OPERATE_PK
"""

import json, time, logging
from datetime import date, datetime, timedelta
from typing import Optional

from data.snapshot_schema import get_conn, SNAPSHOT_VERSION

logger = logging.getLogger(__name__)

_EASTMONEY_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}

_FUNDA_COLS = [
    "SECUCODE", "SECURITY_NAME_ABBR", "REPORT_DATE", "NOTICE_DATE",
    "TOTALOPERATEREVE",         # 营业收入
    "PARENTNETPROFIT",          # 归母净利润
    "DJD_TOI_YOY",              # 营收同比增长率(%)
    "PARENTNETPROFITTZ",        # 净利润同比增长率(%)
    "ROEJQ",                    # ROE(%)
    "XSMLL",                    # 毛利率(%)
    "XSJLL",                    # 净利率(%)
    "ZCFZL",                    # 资产负债率(%)
    "NETCASH_OPERATE_PK",       # 经营现金流净额
]

_DATA_SOURCE = "eastmoney"  # 数据来源，写入 source 字段


def _to_eastmoney_code(code: str) -> str:
    """A股代码 → 东方财富 SECUCODE"""
    prefix = "SH" if code.startswith(("6", "9")) else "SZ"
    return f"{code}.{prefix}"


def _fetch_financial(code: str, page_size: int = 20) -> list[dict]:
    """获取单只股票全部分期的财务数据"""
    em_code = _to_eastmoney_code(code)
    cols = ",".join(_FUNDA_COLS)
    url = (
        f"{_EASTMONEY_BASE}?reportName=RPT_F10_FINANCE_MAINFINADATA"
        f"&columns={cols}"
        f"&pageNumber=1&pageSize={page_size}"
        f"&sortTypes=-1&sortColumns=REPORT_DATE"
        f"&source=WEB&client=WEB"
        f"&filter=(SECUCODE=%22{em_code}%22)"
    )
    try:
        req = __import__("urllib.request").request.Request(url, headers=_HEADERS)
        with __import__("urllib.request").request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
        if data.get("result") and data["result"].get("data"):
            return data["result"]["data"]
    except Exception as e:
        logger.warning(f"{code}: 请求失败 - {e}")
    return []


def _calc_available_time(notice_date_str: str) -> str:
    """公告日期 → 可用时间（公告日 + 1 交易日）"""
    if not notice_date_str:
        return date.today().isoformat()
    try:
        dt = datetime.strptime(notice_date_str[:10], "%Y-%m-%d")
        return (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return date.today().isoformat()


def _safe_float(v, default=None):
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def collect_stock(code: str) -> int:
    """采集单只股票的基本面数据，返回写入行数"""
    rows = _fetch_financial(code)
    if not rows:
        return 0

    conn = get_conn()
    written = 0
    for r in rows:
        report_date = (r.get("REPORT_DATE") or "")[:10]
        notice_date = (r.get("NOTICE_DATE") or "")[:10]
        available_time = _calc_available_time(notice_date)

        if not report_date:
            continue

        fiscal_period = report_date
        try:
            dt = datetime.strptime(report_date, "%Y-%m-%d")
            quarter = (dt.month - 1) // 3 + 1
            fiscal_period = f"{dt.year}Q{quarter}"
        except ValueError:
            pass

        existing = conn.execute(
            "SELECT id FROM fundamental_snapshot "
            "WHERE code=? AND fiscal_period=? AND source=?",
            (code, fiscal_period, _DATA_SOURCE)
        ).fetchone()
        if existing:
            continue

        conn.execute("""
            INSERT INTO fundamental_snapshot
            (code, name, fiscal_period, publish_time, available_time,
             revenue, revenue_yoy, net_profit, net_profit_yoy,
             total_assets, total_liab, equity,
             roe, gross_margin, net_margin,
             source, snapshot_version)
            VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?)
        """, (
            code,
            r.get("SECURITY_NAME_ABBR", "") or "",
            fiscal_period,
            notice_date,               # publish_time = 公告日期
            available_time,            # available_time = 公告日+1
            _safe_float(r.get("TOTALOPERATEREVE")),
            _safe_float(r.get("DJD_TOI_YOY")),
            _safe_float(r.get("PARENTNETPROFIT")),
            _safe_float(r.get("PARENTNETPROFITTZ")),
            None, None, None,
            _safe_float(r.get("ROEJQ")),
            _safe_float(r.get("XSMLL")),
            _safe_float(r.get("XSJLL")),
            _DATA_SOURCE,              # source = 'eastmoney'
            SNAPSHOT_VERSION,
        ))
        written += 1

    if written > 0:
        conn.commit()
    return written


def batch_collect(codes: list[str], batch_size: int = 100) -> dict:
    """批量采集"""
    total = len(codes)
    success = 0
    failed = 0
    total_rows = 0

    for i, code in enumerate(codes):
        try:
            n = collect_stock(code)
            if n > 0:
                success += 1
                total_rows += n
            else:
                failed += 1
        except Exception as e:
            logger.error(f"{code}: {e}")
            failed += 1

        if (i + 1) % 50 == 0:
            logger.info(f"[{i+1}/{total}] 成功{success} 失败{failed} 数据{total_rows}行")

        time.sleep(0.3)

    return {"total": total, "success": success, "failed": failed, "rows": total_rows}


def collect_recent_quarters(months: int = 18) -> dict:
    """采集最近 N 个月的所有财报数据"""
    from scanner.universe import build_stock_pool
    pool = build_stock_pool("A")
    codes = [s.code for s in pool]
    logger.info(f"股票池: {len(codes)} 只, 来源: {_DATA_SOURCE}")
    return batch_collect(codes)
