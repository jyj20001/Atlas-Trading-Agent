"""Atlas Trading Agent — K线数据源一致性验证

比较 东方财富 qfq vs 腾讯 qfq 的 K 线差异。
对 3 只样本股票进行精确对比。

输出: docs/KLINE_PROVIDER_VALIDATION.md
"""

import sys, os, time, json, math
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

SAMPLE = [
    ("600519", "贵州茅台"),  # 沪市蓝筹
    ("000001", "平安银行"),  # 深市主板
    ("300750", "宁德时代"),  # 创业板
]


def fetch_provider(code: str, provider_name: str) -> list[dict]:
    """用指定 Provider 获取 K 线"""
    from data.kline_providers import fetch_from_chain

    if provider_name == "eastmoney":
        # 仅用 EastMoney
        from data.kline_providers.eastmoney_provider import EastMoneyProvider
        p = EastMoneyProvider()
        return p.fetch(code, max_count=2000)

    elif provider_name == "tencent":
        # 仅用 Tencent
        from data.kline_providers.tencent_provider import TencentProvider
        p = TencentProvider()
        return p.fetch(code, max_count=2000)

    return []


def compute_ma(prices: list[float], period: int) -> float:
    if len(prices) < period:
        return 0
    return sum(prices[-period:]) / period


def compute_highest(prices: list[float], period: int) -> float:
    if len(prices) < period:
        return 0
    return max(prices[-period:])


def compare():
    results = {}
    overall_errors = {"close_mae": [], "high_mae": [], "low_mae": []}

    for code, name in SAMPLE:
        logging.info(f"比较 {code} {name}...")
        import logging
        logging.disable(logging.CRITICAL)

        em = fetch_provider(code, "eastmoney")
        tx = fetch_provider(code, "tencent")

        if not em or not tx:
            results[code] = {"name": name, "error": "一个或两个数据源无数据"}
            continue

        # 对齐共同日期
        em_map = {k.trade_date: k for k in em}
        tx_map = {k.trade_date: k for k in tx}
        common_dates = sorted(set(em_map.keys()) & set(tx_map.keys()))

        if not common_dates:
            results[code] = {"name": name, "error": "无共同日期"}
            continue

        # 逐日比较
        errors = []
        for dt in common_dates:
            ek = em_map[dt]
            tk = tx_map[dt]
            close_err = abs(ek.close - tk.close) / max(tk.close, 0.01) * 100
            high_err = abs(ek.high - tk.high) / max(tk.high, 0.01) * 100
            low_err = abs(ek.low - tk.low) / max(tk.low, 0.01) * 100
            errors.append({
                "date": dt,
                "em_close": ek.close, "tx_close": tk.close,
                "close_err_pct": round(close_err, 4),
                "high_err_pct": round(high_err, 4),
                "low_err_pct": round(low_err, 4),
            })

        max_err = max(e["close_err_pct"] for e in errors)
        avg_err = sum(e["close_err_pct"] for e in errors) / len(errors)

        # MA200 对比
        em_closes = [k.close for k in em]
        tx_closes = [k.close for k in tx]
        em_ma200 = compute_ma(em_closes, min(200, len(em_closes)))
        tx_ma200 = compute_ma(tx_closes, min(200, len(tx_closes)))
        ma200_err = abs(em_ma200 - tx_ma200) / max(tx_ma200, 0.01) * 100 if tx_ma200 else 0

        # 20日高对比
        em_20h = compute_highest(em_closes, min(20, len(em_closes)))
        tx_20h = compute_highest(tx_closes, min(20, len(tx_closes)))
        high20_err = abs(em_20h - tx_20h) / max(tx_20h, 0.01) * 100 if tx_20h else 0

        results[code] = {
            "name": name,
            "em_bars": len(em),
            "tx_bars": len(tx),
            "common_dates": len(common_dates),
            "em_earliest": em[0].trade_date if em else "",
            "tx_earliest": tx[0].trade_date if tx else "",
            "close_avg_err_pct": round(avg_err, 3),
            "close_max_err_pct": round(max_err, 3),
            "ma200_em": round(em_ma200, 2),
            "ma200_tx": round(tx_ma200, 2),
            "ma200_err_pct": round(ma200_err, 3),
            "high20_em": round(em_20h, 2),
            "high20_tx": round(tx_20h, 2),
            "high20_err_pct": round(high20_err, 3),
        }

        overall_errors["close_mae"].append(avg_err)
        overall_errors["high_mae"].append(high_err := sum(e["high_err_pct"] for e in errors) / len(errors))
        overall_errors["low_mae"].append(low_err := sum(e["low_err_pct"] for e in errors) / len(errors))

    return results, overall_errors


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    logging.basicConfig(level=logging.INFO)

    results, overall = compare()

    # 生成报告
    lines = []
    w = lambda s="": lines.append(s)
    w("# K-Line Provider Data Consistency Validation Report")
    w("")
    w(f"**日期:** {date.today().isoformat()}")
    w(f"**对比数据源:** 东方财富 qfq vs 腾讯 qfq")
    w("")
    w("## 样本股票")
    w("")
    w("| 代码 | 名称 | 天数(东财) | 天数(腾讯) | 共同日期 | 最早(东财) | 最早(腾讯) |")
    w("|------|------|:----------:|:----------:|:--------:|:----------:|:----------:|")
    for code, r in results.items():
        err = r.get("error", "")
        if err:
            w(f"| {code} | {r.get('name','')} | - | - | - | ❌ {err} | - |")
        else:
            w(f"| {code} | {r['name']} | {r['em_bars']} | {r['tx_bars']} | {r['common_dates']} | {r['em_earliest']} | {r['tx_earliest']} |")
    w("")

    w("## 收盘价误差统计")
    w("")
    w("| 股票 | 平均误差% | 最大误差% |")
    w("|------|:---------:|:---------:|")
    for code, r in results.items():
        if "error" not in r:
            w(f"| {code} {r['name']} | {r['close_avg_err_pct']}% | {r['close_max_err_pct']}% |")
    w("")

    w("## 技术指标对比 (MA200 / 20日高)")
    w("")
    w("| 股票 | MA200(东财) | MA200(腾讯) | 误差% | 20日高(东财) | 20日高(腾讯) | 误差% |")
    w("|------|:-----------:|:-----------:|:-----:|:------------:|:------------:|:-----:|")
    for code, r in results.items():
        if "error" not in r:
            w(f"| {code} {r['name']} | {r['ma200_em']} | {r['ma200_tx']} | {r['ma200_err_pct']}% | {r['high20_em']} | {r['high20_tx']} | {r['high20_err_pct']}% |")
    w("")

    w("## 结论")
    w("")
    all_ok = all(r.get("close_max_err_pct", 999) < 1.0 for r in results.values() if "error" not in r)
    if all_ok:
        w("✅ **通过**: 东方财富与腾讯前复权收盘价误差 < 1%，指标差异在可接受范围内。")
    else:
        w("⚠️ **注意**: 部分股票的误差超过 1%，需要进一步排查。")
    w("")
    w("| 检查项 | 状态 |")
    w("|--------|:----:|")
    for code, r in results.items():
        if "error" not in r:
            status = "✅" if r["close_max_err_pct"] < 1.0 else "⚠️"
            w(f"| {code} close误差 | {status} max={r['close_max_err_pct']}% |")
    w("")

    rp = os.path.expanduser("~/Atlas-Trading-Agent/docs/KLINE_PROVIDER_VALIDATION.md")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告保存: {rp}")
