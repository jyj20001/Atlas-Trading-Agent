"""
Atlas Trading Agent — 研究运行器

自动执行 Research Script，生成报告，验证 Acceptance Criteria 合规性。

用法：
    python research_runner.py R002
    python research_runner.py R002 --force       # 跳过运行前检查（仅调试用）

检查清单（运行前，不通过则拒绝执行）：
  [1] 对应 R00X 文档的 Acceptance Criteria 字段不能为空
  [2] 研究脚本不能直接连接生产数据库路径

检查清单（运行后）：
  [3] Acceptance Criteria 的确定时间必须早于 Result 的写入时间
       → 不通过则报告标记为 INVALID
"""

import argparse
import importlib.util
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ── 项目根路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent
RESEARCH_DIR = PROJECT_ROOT / "research"
DATA_DIR = RESEARCH_DIR / "data"
DOCS_RESEARCH_DIR = PROJECT_ROOT / "docs" / "research"

# ── 生产数据库路径（禁止直连） ──
PRODUCTION_DB_PATTERNS = [
    r"buy_stop_v3/data/market\.db",
    r"buy_stop_v3/data/historical\.db",
    r"buy_stop_v3/data/signals\.db",
    r"data/market\.db",
    r"data/historical\.db",
]

# ── 日期格式（用于 Timestamps 字段解析） ──
DATETIME_FMT = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"


def main():
    parser = argparse.ArgumentParser(description="Atlas Research Runner")
    parser.add_argument("research_id", help="研究编号，如 R002")
    parser.add_argument("--force", action="store_true",
                        help="跳过运行前检查（仅调试用）")
    args = parser.parse_args()

    rid = args.research_id.upper()
    if not re.match(r"^R\d{3}$", rid):
        print(f"❌ 无效的研究编号: {rid}。格式应为 R002, R003 等。")
        sys.exit(1)

    doc_path = DOCS_RESEARCH_DIR / f"{rid}_*.md"
    script_path = RESEARCH_DIR / f"{rid}_*.py"

    print(f"\n{'='*60}")
    print(f"📋 Atlas Research Runner — {rid}")
    print(f"{'='*60}\n")

    # ── 查找文档 ──
    doc_file = _find_file(doc_path, f"研究文档 {rid}")
    if not doc_file:
        sys.exit(1)

    # ── 查找脚本 ──
    script_file = _find_file(script_path, f"研究脚本 {rid}")
    if not script_file:
        sys.exit(1)

    # ── 读取文档内容 ──
    doc_text = doc_file.read_text(encoding="utf-8")

    # ── 运行前检查 ──
    print("--- 运行前检查 ---")

    check1 = _check_acceptance_criteria_not_empty(doc_text, doc_file)
    check2 = _check_no_production_db_connection(script_file)

    if not args.force and (not check1 or not check2):
        print(f"\n❌ {rid}: 运行前检查未通过，拒绝执行。")
        print("   使用 --force 可跳过检查（仅调试用）")
        sys.exit(2)

    if args.force:
        print("   ⚠️  --force 模式：跳过了运行前检查")

    print("   全部检查通过 ✅\n")

    # ── 执行研究脚本 ──
    print(f"--- 执行 {script_file.name} ---")
    sys.path.insert(0, str(RESEARCH_DIR))

    try:
        spec = importlib.util.spec_from_file_location(
            script_file.stem, script_file
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"❌ 脚本执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("   脚本执行完成 ✅\n")

    # ── 运行后检查 ──
    print("--- 运行后检查 ---")

    ac_time, result_time = _extract_timestamps(doc_text)
    check3 = _check_timestamps_order(ac_time, result_time)

    report_valid = check3  # 报告有效性标记

    if not check3:
        print("\n⚠️  ⚠️  ⚠️  最终报告将被标记为 INVALID ⚠️  ⚠️  ⚠️ ")
        print("   Acceptance Criteria 的确定时间不早于 Result 写入时间。")
        print("   这可能是事后修改了标准，结果不予采信。")
        report_valid = False

    # ── 生成报告 ──
    print("\n--- 生成报告 ---")
    report_path = _generate_report(rid, doc_file, doc_text, report_valid)
    print(f"   报告已更新: {report_path}")
    print(f"   有效性: {'✅ 有效' if report_valid else '⚠️ INVALID'}")
    print(f"\n{'='*60}")
    print(f"✅ {rid} 研究完成")
    print(f"{'='*60}")


# ── 文件查找 ──

def _find_file(glob_pattern, label):
    """用 glob 模式查找文件（支持通配符）"""
    import glob
    matches = glob.glob(str(glob_pattern))
    if not matches:
        print(f"❌ 未找到 {label}: {glob_pattern}")
        return None
    if len(matches) > 1:
        print(f"⚠️  找到多个 {label}，使用第一个: {matches[0]}")
    return Path(matches[0])


# ── 运行前检查 1: Acceptance Criteria 不为空 ──

def _check_acceptance_criteria_not_empty(doc_text, doc_path) -> bool:
    """检查 R00X 文档的 Acceptance Criteria 字段是否为空"""
    print(f"   [1] Acceptance Criteria 不为空...")

    # 检查 "### 判定标准" 下面的内容是否为空
    section = _extract_section(doc_text, "### 判定标准", "### ")
    if not section or section.strip() == "":
        print(f"   ❌ 未通过: '判定标准' 字段为空")
        print(f"       → 请在 {doc_path} 中填入具体的统计标准")
        return False

    # 检查 "### 样本要求" 下面的内容是否为空
    sample_section = _extract_section(doc_text, "### 样本要求", "### ")
    if not sample_section or sample_section.strip() == "":
        print(f"   ❌ 未通过: '样本要求' 字段为空")
        print(f"       → 请在 {doc_path} 中填入样本要求")
        return False

    print(f"   ✅ 通过")

    # 额外警告：检查是否包含模糊表述
    vague_phrases = ["达到统计要求", "合理的样本量", "显著改善",
                     "在统计上显著", "达到要求"]
    for phrase in vague_phrases:
        if phrase in section:
            print(f"   ⚠️  警告: '判定标准' 包含模糊表述「{phrase}」")
            print(f"       → 建议替换为具体的阈值（p值、样本量等）")

    return True


# ── 运行前检查 2: 不直连生产数据库 ──

def _check_no_production_db_connection(script_path) -> bool:
    """检查研究脚本是否直接连接生产数据库"""
    print(f"   [2] 不直连生产数据库...")

    script_text = script_path.read_text(encoding="utf-8")

    for pattern in PRODUCTION_DB_PATTERNS:
        if re.search(pattern, script_text):
            print(f"   ❌ 未通过: 检测到生产数据库路径 '{pattern}'")
            print(f"       → 请将数据快照复制到 {DATA_DIR}/ 下使用只读副本")
            return False

    print(f"   ✅ 通过")
    return True


# ── 运行后检查 3: Timestamps 顺序 ──

def _extract_timestamps(doc_text):
    """从文档 Timestamps 表格中提取时间"""
    ac_time = None
    result_time = None

    # 从 Timestamps 表格中提取
    # 格式: | Acceptance Criteria 确定 | YYYY-MM-DD HH:MM |
    ac_match = re.search(
        r"\| Acceptance Criteria 确定 \| (\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
        doc_text
    )
    if ac_match:
        ac_time = ac_match.group(1)

    result_match = re.search(
        r"\| Result 写入 \| (\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
        doc_text
    )
    if result_match:
        result_time = result_match.group(1)

    return ac_time, result_time


def _check_timestamps_order(ac_time, result_time) -> bool:
    """检查 Acceptance Criteria 确定时间是否早于 Result 写入时间"""
    print(f"   [3] Acceptance Criteria 早于 Result 写入...")

    if not ac_time or ac_time.strip() == "—":
        print(f"   ⚠️  跳过: Acceptance Criteria 确定时间未填写")
        return True  # 没填时间说明还没开始，不算违规

    if not result_time or result_time.strip() == "—":
        print(f"   ⚠️  跳过: Result 写入时间未填写")
        return True  # 没写结果说明刚跑完，不算违规

    ac_dt = datetime.strptime(ac_time, "%Y-%m-%d %H:%M")
    result_dt = datetime.strptime(result_time, "%Y-%m-%d %H:%M")

    if ac_dt < result_dt:
        print(f"   ✅ 通过")
        print(f"      Acceptance Criteria: {ac_time}")
        print(f"      Result 写入:        {result_time}")
        return True
    else:
        print(f"   ❌ 未通过")
        print(f"      Acceptance Criteria: {ac_time}")
        print(f"      Result 写入:        {result_time}")
        print(f"      标准确定时间 ({ac_time}) 不早于结果写入时间 ({result_time})")
        return False


# ── 辅助：提取文档节 ──

def _extract_section(text, section_header, next_header_prefix):
    """提取从 section_header 到下一个同级别标题之间的内容"""
    lines = text.split("\n")
    in_section = False
    content = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(section_header):
            in_section = True
            continue
        if in_section and stripped.startswith(next_header_prefix):
            break
        if in_section:
            content.append(line)

    return "\n".join(content).strip()


# ── 报告生成 ──

def _generate_report(rid, doc_path, doc_text, valid: bool) -> Path:
    """生成／更新 R00X 文档的报告部分"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 更新 Timestamps
    new_doc = doc_text
    report_line = f"| 报告生成 | {now} |"

    if re.search(r"\| 报告生成 \|", new_doc):
        new_doc = re.sub(
            r"\| 报告生成 \|.*",
            report_line,
            new_doc,
        )
    else:
        new_doc += f"\n{report_line}"

    # 如果报告无效，在文档末尾追加 INVALID 标记
    if not valid:
        invalid_marker = (
            f"\n\n---\n"
            f"⚠️ **INVALID：验收标准晚于或等同于结果写入时间，不予采信。**\n"
            f"> 检测时间: {now}\n"
        )
        if "⚠️ **INVALID" not in new_doc:
            new_doc += invalid_marker

    doc_path.write_text(new_doc, encoding="utf-8")
    return doc_path


if __name__ == "__main__":
    main()
