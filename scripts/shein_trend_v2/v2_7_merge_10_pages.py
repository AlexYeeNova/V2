"""V2.7：合并 V2.6 十页 CSV，并增强 product_id 去重统计。"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


# 项目根目录、输入文件与输出文件。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_NUMBERS = list(range(1, 11))
INPUT_FILES = {
    page_number: PROJECT_ROOT / "data" / "output" / f"v2_6_products_page_{page_number}.csv"
    for page_number in PAGE_NUMBERS
}
MERGED_OUTPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_7_products_10_pages_merged.csv"
DUPLICATES_OUTPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_7_duplicates_summary.csv"
ENHANCED_FIELDS = ["product_id", "source_page", "appear_count", "appear_pages"]
DUPLICATE_SUMMARY_FIELDS = ["product_id", "appear_count", "appear_pages", "title", "product_url"]


def extract_product_id_from_url(product_url: str) -> str:
    """从 SHEIN 商品 URL 中提取 product_id。"""
    match = re.search(r"-p-(\d+)\.html", product_url)
    if match:
        return match.group(1)

    # 兼容 detailBusinessFrom 等参数中带出的商品 ID。
    match = re.search(r"(?:_|%7C)(\d{6,})(?:%7C|&|$)", product_url)
    if match:
        return match.group(1)

    return ""


def get_product_id(row: dict[str, str]) -> str:
    """优先读取 product_id 字段；若不存在，则从 product_url 中提取。"""
    product_id = (row.get("product_id") or "").strip()
    if product_id:
        return product_id

    product_url = (row.get("product_url") or "").strip()
    return extract_product_id_from_url(product_url)


def read_csv_rows(csv_path: Path, page_number: int) -> tuple[list[dict[str, str]], list[str]]:
    """读取单页 CSV 文件，并给每条记录补充来源页码。"""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 文件不存在：{csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        if "product_id" not in fieldnames and "product_url" not in fieldnames:
            raise ValueError(f"CSV 缺少 product_id 或 product_url 字段：{csv_path}")

        rows = []
        for row in reader:
            row["_source_page_number"] = str(page_number)
            rows.append(row)
        return rows, fieldnames


def merge_fieldnames(fieldname_groups: list[list[str]]) -> list[str]:
    """合并多个 CSV 字段名，并把增强字段放在输出前列。"""
    merged_fieldnames: list[str] = []
    for fieldname in ENHANCED_FIELDS:
        if fieldname not in merged_fieldnames:
            merged_fieldnames.append(fieldname)

    for fieldnames in fieldname_groups:
        for fieldname in fieldnames:
            if fieldname not in merged_fieldnames:
                merged_fieldnames.append(fieldname)

    return merged_fieldnames


def format_appear_pages(page_numbers: set[int]) -> str:
    """将出现页码集合格式化为稳定的逗号分隔字符串。"""
    return ",".join(str(page_number) for page_number in sorted(page_numbers))


def merge_and_deduplicate(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], Counter[str], dict[str, set[int]], dict[str, dict[str, str]]]:
    """合并全部记录，按 product_id 保留首次出现记录，并统计出现次数和页码。"""
    product_id_counter: Counter[str] = Counter()
    product_id_pages: dict[str, set[int]] = defaultdict(set)
    first_rows: dict[str, dict[str, str]] = {}
    deduplicated_rows: list[dict[str, str]] = []

    for row in rows:
        product_id = get_product_id(row)
        if not product_id:
            continue

        source_page = int(row.get("_source_page_number") or 0)
        product_id_counter[product_id] += 1
        if source_page > 0:
            product_id_pages[product_id].add(source_page)

        if product_id in first_rows:
            continue

        first_row = dict(row)
        first_row["product_id"] = product_id
        first_row["source_page"] = str(source_page)
        first_rows[product_id] = first_row
        deduplicated_rows.append(first_row)

    for row in deduplicated_rows:
        product_id = row["product_id"]
        row["appear_count"] = str(product_id_counter[product_id])
        row["appear_pages"] = format_appear_pages(product_id_pages[product_id])

    return deduplicated_rows, product_id_counter, product_id_pages, first_rows


def build_duplicate_summary_rows(
    product_id_counter: Counter[str],
    product_id_pages: dict[str, set[int]],
    first_rows: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """生成重复商品摘要，只包含出现次数大于 1 的 product_id。"""
    duplicate_rows: list[dict[str, str]] = []
    for product_id, appear_count in product_id_counter.most_common():
        if appear_count <= 1:
            continue

        first_row = first_rows[product_id]
        duplicate_rows.append(
            {
                "product_id": product_id,
                "appear_count": str(appear_count),
                "appear_pages": format_appear_pages(product_id_pages[product_id]),
                "title": first_row.get("title", ""),
                "product_url": first_row.get("product_url", ""),
            }
        )

    return duplicate_rows


def save_csv(rows: list[dict[str, str]], output_file: Path, fieldnames: list[str]) -> None:
    """保存 CSV 文件。"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def calc_duplicate_rate(total_count: int, deduplicated_count: int) -> float:
    """计算重复率。"""
    if total_count <= 0:
        return 0.0
    return (total_count - deduplicated_count) / total_count


def print_top10_products(product_id_counter: Counter[str], first_rows: dict[str, dict[str, str]]) -> None:
    """输出出现次数最高的前 10 个重复商品。"""
    duplicate_items = [
        (product_id, count)
        for product_id, count in product_id_counter.most_common()
        if count > 1
    ][:10]

    print()
    print("出现次数最高 Top10 商品：")
    if not duplicate_items:
        print("无重复商品")
        return

    for index, (product_id, count) in enumerate(duplicate_items, start=1):
        title = first_rows[product_id].get("title", "")
        print(f"{index}. product_id={product_id}，出现次数={count}，标题={title}")


def main() -> None:
    """执行 V2.7 十页数据合并与增强去重流程。"""
    all_rows: list[dict[str, str]] = []
    fieldname_groups: list[list[str]] = []

    for page_number, input_file in INPUT_FILES.items():
        rows, fieldnames = read_csv_rows(input_file, page_number)
        all_rows.extend(rows)
        fieldname_groups.append(fieldnames)

    output_fieldnames = merge_fieldnames(fieldname_groups)
    deduplicated_rows, product_id_counter, product_id_pages, first_rows = merge_and_deduplicate(all_rows)
    duplicate_summary_rows = build_duplicate_summary_rows(product_id_counter, product_id_pages, first_rows)

    save_csv(deduplicated_rows, MERGED_OUTPUT_FILE, output_fieldnames)
    save_csv(duplicate_summary_rows, DUPLICATES_OUTPUT_FILE, DUPLICATE_SUMMARY_FIELDS)

    original_count = len(all_rows)
    deduplicated_count = len(deduplicated_rows)
    removed_duplicate_count = original_count - deduplicated_count
    duplicate_rate = calc_duplicate_rate(original_count, deduplicated_count)

    print("V2.7 十页数据合并增强去重结果")
    print("=" * 48)
    print(f"原始总记录数：{original_count}")
    print(f"去重后记录数：{deduplicated_count}")
    print(f"删除重复数量：{removed_duplicate_count}")
    print(f"重复率：{duplicate_rate:.2%}")
    print(f"合并 CSV 保存路径：{MERGED_OUTPUT_FILE}")
    print(f"重复摘要 CSV 保存路径：{DUPLICATES_OUTPUT_FILE}")
    print_top10_products(product_id_counter, first_rows)


if __name__ == "__main__":
    main()
