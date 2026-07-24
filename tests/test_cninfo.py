"""
Buy Stop V3 — 巨潮资讯数据抓取模块 单独测试脚本

用法:
  python test_cninfo.py                    # 运行所有测试
  python test_cninfo.py forecast           # 只测试 业绩预告
  python test_cninfo.py report             # 只测试 业绩快报
  python test_cninfo.py stock 000977       # 测试个股公告查询
  python test_cninfo.py orgid 000977       # 测试获取 orgId
"""

import sys
import json
from datetime import date, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "buy_stop_v3"))

from data.cninfo_fetcher import (
    search_performance_forecasts,
    search_performance_reports,
    search_stock_announcements,
    get_stock_org_id,
)
from utils.logger import logger

# 测试日期范围
TODAY = date.today()
START = (TODAY - timedelta(days=7)).isoformat()
END = TODAY.isoformat()


def test_01_forecast():
    """测试① 搜索业绩预告"""
    print(f"\n{'='*60}")
    print(f"测试①: 搜索业绩预告 ({START} ~ {END})")
    print(f"{'='*60}")

    results = search_performance_forecasts(
        start_date=START,
        end_date=END,
        page=1,
        page_size=10,
    )

    assert isinstance(results, list), "返回类型应为 list"
    print(f"  结果数量: {len(results)}")

    if len(results) > 0:
        r = results[0]
        assert hasattr(r, 'code'), "应包含 code"
        assert hasattr(r, 'name'), "应包含 name"
        assert hasattr(r, 'announce_date'), "应包含 announce_date"
        assert hasattr(r, 'forecast_type'), "应包含 forecast_type"
        print(f"  第一条: [{r.announce_date}] {r.code} {r.name} - {r.forecast_type}")
    else:
        print("  ⚠️ 时间段内无业绩预告（可能今天非交易日）")

    return results


def test_02_report():
    """测试② 搜索业绩快报"""
    print(f"\n{'='*60}")
    print(f"测试②: 搜索业绩快报 ({START} ~ {END})")
    print(f"{'='*60}")

    results = search_performance_reports(
        start_date=START,
        end_date=END,
        page=1,
        page_size=10,
    )

    assert isinstance(results, list), "返回类型应为 list"
    print(f"  结果数量: {len(results)}")

    if len(results) > 0:
        r = results[0]
        print(f"  第一条: [{r.announce_date}] {r.code} {r.name} - {r.forecast_type}")
    else:
        print(f"  ⚠️ 时间段内无业绩快报")

    return results


def test_03_stock_announcements(stock_code: str = "000977"):
    """测试③ 查询个股公告"""
    print(f"\n{'='*60}")
    print(f"测试③: 查询个股公告 - {stock_code} (业绩预告)")
    print(f"{'='*60}")

    results = search_stock_announcements(
        stock_code=stock_code,
        keyword="业绩预告",
        start_date="2026-01-01",
        end_date=END,
    )

    assert isinstance(results, list), "返回类型应为 list"
    print(f"  结果数量: {len(results)}")

    if len(results) > 0:
        r = results[0]
        print(f"  第一条: [{r['date']}] {r['code']} {r['name']}")
        print(f"  标题: {r['title'][:60]}")
        assert 'title' in r, "应包含 title"
        assert 'date' in r, "应包含 date"
        assert 'pdf_url' in r, "应包含 pdf_url"
        if r['pdf_url']:
            print(f"  PDF: {r['pdf_url'][:80]}...")
    else:
        print(f"  ⚠️ 无结果")

    return results


def test_04_org_id(stock_code: str = "000977"):
    """测试④ 获取股票 orgId"""
    print(f"\n{'='*60}")
    print(f"测试④: 获取 orgId - {stock_code}")
    print(f"{'='*60}")

    org_id = get_stock_org_id(stock_code)

    if org_id:
        print(f"  orgId: {org_id}")
        assert org_id.startswith("gs"), f"orgId 格式异常: {org_id}"
    else:
        print(f"  ⚠️ 无法获取 orgId")

    return org_id


def test_05_batch_stocks():
    """测试⑤ 批量查询多个热门股的业绩预告"""
    print(f"\n{'='*60}")
    print(f"测试⑤: 批量查询 (多只股票近期业绩提示)")
    print(f"{'='*60}")

    stocks_to_check = ["000977", "002594", "300750", "000063", "600519"]
    total_found = 0

    for code in stocks_to_check:
        results = search_stock_announcements(
            stock_code=code,
            keyword="业绩预告",
            start_date="2026-06-01",
            end_date=END,
        )
        if results:
            r = results[0]
            print(f"  {code}: [{r['date']}] {r['title'][:50]}")
            total_found += 1
        else:
            print(f"  {code}: 无业绩预告")

    print(f"\n  共查 {len(stocks_to_check)} 只, 找到业绩预告: {total_found} 只")
    return total_found


# ── 主入口 ──

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or "all" in args:
        print(f"\n📋 Buy Stop V3 — 巨潮资讯模块测试")
        print(f"   日期范围: {START} ~ {END}")
        print(f"   {'='*40}")

        test_01_forecast()
        test_02_report()
        test_03_stock_announcements()
        test_04_org_id()
        test_05_batch_stocks()
        print(f"\n{'='*60}")
        print("✅ 全部测试完成")
        print(f"{'='*60}")

    elif "forecast" in args:
        test_01_forecast()

    elif "report" in args:
        test_02_report()

    elif "stock" in args:
        code = args[args.index("stock") + 1] if len(args) > args.index("stock") + 1 else "000977"
        test_03_stock_announcements(code)

    elif "orgid" in args:
        code = args[args.index("orgid") + 1] if len(args) > args.index("orgid") + 1 else "000977"
        test_04_org_id(code)

    elif "batch" in args:
        test_05_batch_stocks()

    else:
        print(f"未知参数: {args}")
        print(f"用法: python test_cninfo.py [forecast|report|stock|orgid|batch|all]")
