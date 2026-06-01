"""V2.6：连续采集 SHEIN 女装类目 Page1~Page10，并分别保存结果。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import v2_3_fetch_one_page as v23


# 项目根目录、目标页码与 V2.6 固定输出目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_NUMBERS = list(range(1, 11))
DEBUG_DIR = PROJECT_ROOT / "data" / "debug"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"


@dataclass
class PageResult:
    """记录单页采集结果，便于最终汇总。"""

    page_number: int
    current_url: str
    product_count: int
    page_status: str
    result_suggestion: str
    csv_path: Path
    debug_html_path: Path


def build_v2_6_csv_path(page_number: int) -> Path:
    """生成 V2.6 指定页 CSV 保存路径。"""
    return OUTPUT_DIR / f"v2_6_products_page_{page_number}.csv"


def build_v2_6_debug_html_path(page_number: int) -> Path:
    """生成 V2.6 指定页调试 HTML 保存路径。"""
    return DEBUG_DIR / f"v2_6_page_{page_number}.html"


def save_products_csv(products: list[dict[str, str]], csv_path: Path) -> None:
    """按照 V2.3 字段顺序保存商品数据到 CSV。"""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=v23.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(products)


def save_debug_html(page: Any, debug_html_path: Path) -> None:
    """保存当前页 HTML，便于后续排查页面结构和风控状态。"""
    debug_html_path.parent.mkdir(parents=True, exist_ok=True)
    debug_html_path.write_text(str(page.html_content), encoding="utf-8")


def save_error_debug_html(error: Exception, target_url: str, debug_html_path: Path) -> None:
    """当页面请求异常时，仍然落一份调试 HTML，避免十页输出缺文件。"""
    debug_html_path.parent.mkdir(parents=True, exist_ok=True)
    debug_html_path.write_text(
        "\n".join(
            [
                "<!doctype html>",
                "<html>",
                "<head><meta charset=\"utf-8\"><title>V2.6 fetch error</title></head>",
                "<body>",
                "<h1>V2.6 页面采集异常</h1>",
                f"<p>目标 URL：{target_url}</p>",
                f"<pre>{type(error).__name__}: {error}</pre>",
                "</body>",
                "</html>",
            ]
        ),
        encoding="utf-8",
    )


def print_page_result(result: PageResult) -> None:
    """输出单页采集完成后的关键结果。"""
    print("=" * 60)
    print(f"当前采集页码：{result.page_number}")
    print(f"当前 URL：{result.current_url}")
    print(f"商品数量：{result.product_count}")
    print(f"页面状态判断：{result.page_status}")
    print(f"本次结果建议：{result.result_suggestion}")
    print(f"CSV 保存路径：{result.csv_path}")


def print_summary(results: list[PageResult]) -> None:
    """输出十页连续采集汇总结果。"""
    status_counts = {
        "normal_page": 0,
        "verification_suspected": 0,
        "challenge_page": 0,
    }
    for result in results:
        if result.page_status in status_counts:
            status_counts[result.page_status] += 1

    page_counts = [result.product_count for result in results]
    print("=" * 60)
    print("V2.6 Page1~Page10 连续采集汇总")
    print(f"目标页数：{len(PAGE_NUMBERS)}")
    print(f"实际完成页数：{len(results)}")
    print(f"normal_page 页数：{status_counts['normal_page']}")
    print(f"verification_suspected 页数：{status_counts['verification_suspected']}")
    print(f"challenge_page 页数：{status_counts['challenge_page']}")
    print(f"总商品数量：{sum(page_counts)}")
    print(f"每页商品数量列表：{page_counts}")


def fetch_one_page(session: v23.StealthySession, page_number: int) -> PageResult:
    """采集单个页码，并保证 CSV 与调试 HTML 都会单独保存。"""
    target_url = v23.build_target_url(page_number)
    csv_path = build_v2_6_csv_path(page_number)
    debug_html_path = build_v2_6_debug_html_path(page_number)
    crawl_time = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    try:
        page = v23.fetch_page_with_real_chrome(session, target_url)
        products, page_status, result_suggestion, _status_signals = v23.build_products_and_status(page, crawl_time)
        save_products_csv(products, csv_path)
        save_debug_html(page, debug_html_path)
        return PageResult(
            page_number=page_number,
            current_url=v23.normalize_text(page.url),
            product_count=len(products),
            page_status=page_status,
            result_suggestion=result_suggestion,
            csv_path=csv_path,
            debug_html_path=debug_html_path,
        )
    except Exception as error:
        # 单页请求异常不直接中断整轮任务，保留空 CSV 和错误 HTML 方便复盘。
        save_products_csv([], csv_path)
        save_error_debug_html(error, target_url, debug_html_path)
        return PageResult(
            page_number=page_number,
            current_url=target_url,
            product_count=0,
            page_status="fetch_error",
            result_suggestion=f"该页采集异常，已保存空 CSV 和错误调试 HTML：{type(error).__name__}: {error}",
            csv_path=csv_path,
            debug_html_path=debug_html_path,
        )


def main() -> None:
    """执行 Page1~Page10 连续采集，单页异常后继续后续页。"""
    v23.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    results: list[PageResult] = []
    with v23.StealthySession(
        real_chrome=True,
        headless=False,
        user_data_dir=str(v23.BROWSER_PROFILE_DIR),
    ) as session:
        for page_number in PAGE_NUMBERS:
            result = fetch_one_page(session, page_number)
            results.append(result)
            print_page_result(result)

    print_summary(results)


if __name__ == "__main__":
    main()
