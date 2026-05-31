"""V2.5：合并 V2.4 多页 CSV，并按 product_id 去重。"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path


# 项目根目录、输入文件与合并后输出文件。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_NUMBERS = [1, 2, 3, 4, 5]
INPUT_FILES = [
    PROJECT_ROOT / "data" / "output" / f"v2_4_products_page_{page_number}.csv"
    for page_number in PAGE_NUMBERS
]
OUTPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_5_products_merged.csv"


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


def read_csv_rows(csv_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """读取单个 CSV 文件，返回记录列表和字段名。"""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 文件不存在：{csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        if "product_id" not in fieldnames and "product_url" not in fieldnames:
            raise ValueError(f"CSV 缺少 product_id 或 product_url 字段：{csv_path}")
        return list(reader), fieldnames


def merge_fieldnames(fieldname_groups: list[list[str]]) -> list[str]:
    """合并多个 CSV 的字段名，并确保输出包含 product_id。"""
    merged_fieldnames: list[str] = []
    for fieldnames in fieldname_groups:
        for fieldname in fieldnames:
            if fieldname not in merged_fieldnames:
                merged_fieldnames.append(fieldname)

    if "product_id" not in merged_fieldnames:
        merged_fieldnames.insert(0, "product_id")
    return merged_fieldnames


def merge_and_deduplicate(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], Counter[str]]:
    """合并全部记录，并按 product_id 保留第一条记录。"""
    product_id_counter: Counter[str] = Counter()
    seen_product_ids: set[str] = set()
    deduplicated_rows: list[dict[str, str]] = []

    for row in rows:
        product_id = get_product_id(row)
        if not product_id:
            continue

        product_id_counter[product_id] += 1
        if product_id in seen_product_ids:
            continue

        row["product_id"] = product_id
        seen_product_ids.add(product_id)
        deduplicated_rows.append(row)

    return deduplicated_rows, product_id_counter


def save_merged_csv(rows: list[dict[str, str]], output_file: Path, fieldnames: list[str]) -> None:
    """保存去重后的合并 CSV。"""
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


def print_duplicate_top10(product_id_counter: Counter[str]) -> None:
    """输出重复次数最高的前 10 个 product_id。"""
    duplicate_items = [
        (product_id, count)
        for product_id, count in product_id_counter.most_common()
        if count > 1
    ][:10]

    print()
    print("重复次数最高的前 10 个 product_id：")
    if not duplicate_items:
        print("无重复 product_id")
        return

    for index, (product_id, count) in enumerate(duplicate_items, start=1):
        print(f"{index}. product_id={product_id}，重复次数={count}")


def main() -> None:
    """执行 V2.5 数据合并与去重流程。"""
    all_rows: list[dict[str, str]] = []
    fieldname_groups: list[list[str]] = []

    for input_file in INPUT_FILES:
        rows, fieldnames = read_csv_rows(input_file)
        all_rows.extend(rows)
        fieldname_groups.append(fieldnames)

    output_fieldnames = merge_fieldnames(fieldname_groups)
    deduplicated_rows, product_id_counter = merge_and_deduplicate(all_rows)
    save_merged_csv(deduplicated_rows, OUTPUT_FILE, output_fieldnames)

    original_count = len(all_rows)
    deduplicated_count = len(deduplicated_rows)
    removed_duplicate_count = original_count - deduplicated_count
    duplicate_rate = calc_duplicate_rate(original_count, deduplicated_count)

    print("V2.5 数据合并与去重结果")
    print("=" * 40)
    print(f"原始总记录数：{original_count}")
    print(f"去重后记录数：{deduplicated_count}")
    print(f"删除重复数量：{removed_duplicate_count}")
    print(f"重复率：{duplicate_rate:.2%}")
    print(f"合并 CSV 保存路径：{OUTPUT_FILE}")
    print_duplicate_top10(product_id_counter)


if __name__ == "__main__":
    main()
