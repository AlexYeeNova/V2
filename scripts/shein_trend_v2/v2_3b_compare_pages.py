"""V2.3B：对比 V2.3 Page1~Page5 CSV，验证分页数据差异。"""

from __future__ import annotations

import csv
from pathlib import Path


# 项目根目录与固定读取的 V2.3 Page1~Page5 CSV 文件。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_NUMBERS = [1, 2, 3, 4, 5]
PAGE_FILES = {
    page: PROJECT_ROOT / "data" / "output" / f"v2_3_products_page_{page}.csv"
    for page in PAGE_NUMBERS
}


def read_product_urls(csv_path: Path) -> set[str]:
    """读取 CSV 中的 product_url，并作为商品唯一标识去重。"""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 文件不存在：{csv_path}")

    product_urls: set[str] = set()
    with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        if "product_url" not in (reader.fieldnames or []):
            raise ValueError(f"CSV 缺少 product_url 字段：{csv_path}")

        for row in reader:
            product_url = (row.get("product_url") or "").strip()
            if product_url:
                product_urls.add(product_url)

    return product_urls


def calc_repeat_rate(repeat_count: int, left_count: int, right_count: int) -> float:
    """计算两页之间的重复率，分母取相邻两页中较小的商品数量。"""
    base_count = min(left_count, right_count)
    if base_count <= 0:
        return 0.0
    return repeat_count / base_count


def calc_overall_repeat_rate(total_count: int, unique_count: int) -> float:
    """计算五页整体重复率。"""
    if total_count <= 0:
        return 0.0
    return (total_count - unique_count) / total_count


def judge_pagination(overall_repeat_rate: float, adjacent_rates: list[float], total_count: int, unique_count: int) -> str:
    """根据整体重复率和相邻页重复率判断分页有效性。"""
    if total_count <= 0:
        return "分页无效"

    # 如果五页合并后与单页规模接近，说明多页大概率采到了同一批商品。
    if unique_count <= total_count / len(PAGE_NUMBERS) * 1.2:
        return "分页无效"

    max_adjacent_rate = max(adjacent_rates) if adjacent_rates else 0.0
    if overall_repeat_rate >= 0.80 or max_adjacent_rate >= 0.95:
        return "分页无效"
    if overall_repeat_rate >= 0.30 or max_adjacent_rate >= 0.50:
        return "分页部分有效"
    return "分页有效"


def main() -> None:
    """执行本地 CSV 分页差异验证，不访问 SHEIN。"""
    page_urls = {page: read_product_urls(csv_path) for page, csv_path in PAGE_FILES.items()}
    page_counts = {page: len(urls) for page, urls in page_urls.items()}

    adjacent_pairs = [(1, 2), (2, 3), (3, 4), (4, 5)]
    adjacent_stats = []
    for left_page, right_page in adjacent_pairs:
        repeat_count = len(page_urls[left_page] & page_urls[right_page])
        repeat_rate = calc_repeat_rate(repeat_count, page_counts[left_page], page_counts[right_page])
        adjacent_stats.append((left_page, right_page, repeat_count, repeat_rate))

    total_count = sum(page_counts.values())
    unique_urls = set().union(*(page_urls[page] for page in PAGE_NUMBERS))
    unique_count = len(unique_urls)
    overall_repeat_rate = calc_overall_repeat_rate(total_count, unique_count)
    adjacent_rates = [repeat_rate for _, _, _, repeat_rate in adjacent_stats]
    conclusion = judge_pagination(overall_repeat_rate, adjacent_rates, total_count, unique_count)

    print("V2.3B Page1~Page5 分页数据差异验证结果")
    print("=" * 44)
    for page in PAGE_NUMBERS:
        print(f"Page{page} 商品数量：{page_counts[page]}")

    print()
    print("相邻分页重复情况：")
    for left_page, right_page, repeat_count, repeat_rate in adjacent_stats:
        print(
            f"Page{left_page} vs Page{right_page}："
            f"重复数量 {repeat_count}，重复率 {repeat_rate:.2%}"
        )

    print()
    print(f"5页商品总数：{total_count}")
    print(f"5页去重后商品总数：{unique_count}")
    print(f"总体重复率：{overall_repeat_rate:.2%}")
    print(f"分页有效性判断：{conclusion}")


if __name__ == "__main__":
    main()
