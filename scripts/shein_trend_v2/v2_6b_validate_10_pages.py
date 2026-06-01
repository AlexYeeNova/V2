"""V2.6B：验证 V2.6 Page1~Page10 连续采集结果的分页有效性。"""

from __future__ import annotations

import csv
import re
from pathlib import Path


# 项目根目录与固定读取的 V2.6 Page1~Page10 CSV 文件。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_NUMBERS = list(range(1, 11))
PAGE_FILES = {
    page: PROJECT_ROOT / "data" / "output" / f"v2_6_products_page_{page}.csv"
    for page in PAGE_NUMBERS
}
ADJACENT_PAIRS = [
    (left_page, left_page + 1)
    for left_page in range(1, 10)
]


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


def read_page_product_ids(csv_path: Path) -> tuple[int, set[str]]:
    """读取单页 CSV，返回商品总行数与去重后的 product_id 集合。"""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 文件不存在：{csv_path}")

    total_count = 0
    product_ids: set[str] = set()
    with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        if "product_id" not in fieldnames and "product_url" not in fieldnames:
            raise ValueError(f"CSV 缺少 product_id 或 product_url 字段：{csv_path}")

        for row in reader:
            total_count += 1
            product_id = get_product_id(row)
            if product_id:
                product_ids.add(product_id)

    return total_count, product_ids


def calc_overlap_rate(overlap_count: int, left_unique_count: int, right_unique_count: int) -> float:
    """计算相邻两页重叠率，分母取两页唯一商品数中的较小值。"""
    base_count = min(left_unique_count, right_unique_count)
    if base_count <= 0:
        return 0.0
    return overlap_count / base_count


def judge_adjacent_page(overlap_rate: float) -> str:
    """根据相邻页重叠率判断分页是否有效。"""
    if overlap_rate < 0.30:
        return "VALID_PAGE"
    return "SUSPECTED_DUPLICATE_PAGE"


def calc_global_duplicate_rate(total_count: int, global_unique_count: int) -> float:
    """计算十页整体重复率。"""
    if total_count <= 0:
        return 0.0
    return (total_count - global_unique_count) / total_count


def judge_overall_pagination(adjacent_judgements: list[str]) -> str:
    """根据所有相邻页判断结果，给出最终分页有效性判断。"""
    if all(judgement == "VALID_PAGE" for judgement in adjacent_judgements):
        return "Page1~Page10 分页有效"
    return "Page1~Page10 存在疑似重复分页"


def main() -> None:
    """执行 V2.6 十页采集结果验证，不访问 SHEIN 网站。"""
    page_total_counts: dict[int, int] = {}
    page_unique_ids: dict[int, set[str]] = {}

    for page_number, csv_path in PAGE_FILES.items():
        total_count, product_ids = read_page_product_ids(csv_path)
        page_total_counts[page_number] = total_count
        page_unique_ids[page_number] = product_ids

    print("V2.6B Page1~Page10 分页有效性验证")
    print("=" * 52)
    print("每页商品数量：")
    for page_number in PAGE_NUMBERS:
        print(f"Page{page_number} 商品数：{page_total_counts[page_number]}")

    print()
    print("每页唯一商品数量：")
    for page_number in PAGE_NUMBERS:
        print(f"Page{page_number} 唯一商品数：{len(page_unique_ids[page_number])}")

    print()
    print("相邻页重叠结果：")
    adjacent_judgements: list[str] = []
    for left_page, right_page in ADJACENT_PAIRS:
        left_ids = page_unique_ids[left_page]
        right_ids = page_unique_ids[right_page]
        overlap_count = len(left_ids & right_ids)
        overlap_rate = calc_overlap_rate(overlap_count, len(left_ids), len(right_ids))
        page_judgement = judge_adjacent_page(overlap_rate)
        adjacent_judgements.append(page_judgement)
        print(
            f"Page{left_page} vs Page{right_page}："
            f"overlap_count={overlap_count}，"
            f"overlap_rate={overlap_rate:.2%}，"
            f"判断={page_judgement}"
        )

    total_count = sum(page_total_counts.values())
    global_unique_ids = set().union(*(page_unique_ids[page_number] for page_number in PAGE_NUMBERS))
    global_unique_count = len(global_unique_ids)
    global_duplicate_rate = calc_global_duplicate_rate(total_count, global_unique_count)
    overall_judgement = judge_overall_pagination(adjacent_judgements)

    print()
    print("10页全局汇总：")
    print(f"10页总商品数：{total_count}")
    print(f"10页全局唯一商品数：{global_unique_count}")
    print(f"10页全局重复率：{global_duplicate_rate:.2%}")
    print(f"最终分页有效性判断：{overall_judgement}")


if __name__ == "__main__":
    main()
