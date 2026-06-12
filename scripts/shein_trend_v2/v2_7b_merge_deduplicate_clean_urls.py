"""V2.7B: merge ten V2.6 CSV files, deduplicate products, and clean detail URLs."""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_NUMBERS = list(range(1, 11))
INPUT_FILES = {
    page_number: PROJECT_ROOT / "data" / "output" / f"v2_6_products_page_{page_number}.csv"
    for page_number in PAGE_NUMBERS
}
MERGED_OUTPUT_FILE = (
    PROJECT_ROOT / "data" / "output" / "v2_7b_products_10_pages_merged_clean_urls.csv"
)
AUDIT_OUTPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_7b_url_cleaning_audit.csv"
DUPLICATES_OUTPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_7b_duplicates_summary.csv"

ENHANCED_FIELDS = ["product_id", "source_page", "appear_count", "appear_pages"]
URL_CLEANING_FIELDS = [
    "product_url_original",
    "product_url_clean",
    "url_query_removed",
    "removed_query_keys",
    "has_risk_marker",
    "risk_marker_keywords",
    "url_product_id",
    "product_id_match",
]
DUPLICATE_SUMMARY_FIELDS = [
    "product_id",
    "appear_count",
    "appear_pages",
    "title",
    "product_url",
]
AUDIT_FIELDS = [
    "total_raw_rows",
    "total_merged_rows",
    "duplicate_removed_count",
    "duplicate_rate",
    "urls_with_query",
    "urls_cleaned",
    "urls_with_src_module",
    "urls_with_src_identifier",
    "urls_with_src_tab_page_id",
    "urls_with_risk_marker",
    "product_id_mismatch_count",
    "clean_url_duplicate_count",
    "real_sold_rows",
    "real_sold_urls_with_risk_marker",
]
RISK_MARKER_KEYWORDS = [
    "page_risk",
    "crawler",
    "risk",
    "PRODUCT_RECOMMEND",
    "RealClassFilteredRecommend",
    "src_module",
    "src_identifier",
    "src_tab_page_id",
]


def extract_product_id_from_url(product_url: str) -> str:
    """Extract a SHEIN product ID from a detail URL."""
    match = re.search(r"-p-(\d+)\.html", product_url or "", re.IGNORECASE)
    if match:
        return match.group(1)

    match = re.search(r"(?:_|%7C)(\d{6,})(?:%7C|&|$)", product_url or "", re.IGNORECASE)
    return match.group(1) if match else ""


def get_product_id(row: dict[str, str]) -> str:
    """Prefer the CSV product_id and fall back to extracting it from product_url."""
    product_id = (row.get("product_id") or "").strip()
    if product_id:
        return product_id
    return extract_product_id_from_url((row.get("product_url") or "").strip())


def read_csv_rows(csv_path: Path, page_number: int) -> tuple[list[dict[str, str]], list[str]]:
    """Read one V2.6 page and attach its source page number."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 文件不存在：{csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        if "product_id" not in fieldnames and "product_url" not in fieldnames:
            raise ValueError(f"CSV 缺少 product_id 或 product_url 字段：{csv_path}")

        rows: list[dict[str, str]] = []
        for row in reader:
            row["_source_page_number"] = str(page_number)
            rows.append(row)
        return rows, fieldnames


def merge_fieldnames(fieldname_groups: list[list[str]]) -> list[str]:
    """Merge input fields while preserving V2.7 enhanced fields and URL audit fields."""
    merged_fieldnames: list[str] = list(ENHANCED_FIELDS)
    for fieldnames in fieldname_groups:
        for fieldname in fieldnames:
            if fieldname not in merged_fieldnames:
                merged_fieldnames.append(fieldname)
    for fieldname in URL_CLEANING_FIELDS:
        if fieldname not in merged_fieldnames:
            merged_fieldnames.append(fieldname)
    return merged_fieldnames


def format_appear_pages(page_numbers: set[int]) -> str:
    """Format source page numbers as a stable comma-separated string."""
    return ",".join(str(page_number) for page_number in sorted(page_numbers))


def merge_and_deduplicate(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], Counter[str], dict[str, set[int]], dict[str, dict[str, str]]]:
    """Keep the first row for each product_id and preserve V2.7 appearance statistics."""
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


def unique_in_order(values: list[str]) -> list[str]:
    """Return non-empty values once, preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def clean_product_url(product_url: str) -> dict[str, str]:
    """Remove query and fragment data while retaining scheme, host, and path."""
    original_url = (product_url or "").strip()
    parsed = urlsplit(original_url)
    query_keys = unique_in_order([key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)])
    clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    original_lower = original_url.lower()
    matched_markers = [
        keyword
        for keyword in RISK_MARKER_KEYWORDS
        if keyword.lower() in original_lower
    ]

    return {
        "product_url_original": original_url,
        "product_url_clean": clean_url,
        "url_query_removed": str(bool(parsed.query)),
        "removed_query_keys": ",".join(query_keys),
        "has_risk_marker": str(bool(matched_markers)),
        "risk_marker_keywords": ",".join(matched_markers),
        "url_product_id": extract_product_id_from_url(clean_url),
    }


def apply_url_cleaning(rows: list[dict[str, str]]) -> None:
    """Add URL audit fields and replace product_url with the clean detail URL."""
    for row in rows:
        url_fields = clean_product_url(row.get("product_url", ""))
        row.update(url_fields)
        row["product_url"] = url_fields["product_url_clean"]
        row["product_id_match"] = str(
            bool(url_fields["url_product_id"])
            and url_fields["url_product_id"] == (row.get("product_id") or "").strip()
        )


def build_duplicate_summary_rows(
    product_id_counter: Counter[str],
    product_id_pages: dict[str, set[int]],
    first_rows: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Build a descending duplicate-product summary, including at least the top 20."""
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
                "product_url": clean_product_url(first_row.get("product_url", ""))["product_url_clean"],
            }
        )
    return duplicate_rows


def is_real_sold_row(row: dict[str, str]) -> bool:
    """Treat non-empty sales tags containing 'sold' as real sold signals."""
    sales_tag = (row.get("sales_tag") or "").strip().lower()
    return bool(sales_tag and "sold" in sales_tag)


def calc_duplicate_rate(total_count: int, deduplicated_count: int) -> float:
    """Calculate the V2.7 duplicate rate."""
    if total_count <= 0:
        return 0.0
    return (total_count - deduplicated_count) / total_count


def count_clean_url_duplicates(rows: list[dict[str, str]]) -> int:
    """Count excess rows sharing the same non-empty clean URL."""
    clean_urls = [row.get("product_url_clean", "") for row in rows if row.get("product_url_clean")]
    return len(clean_urls) - len(set(clean_urls))


def build_audit_row(total_raw_rows: int, rows: list[dict[str, str]]) -> dict[str, str]:
    """Build the one-row V2.7B URL cleaning audit."""
    total_merged_rows = len(rows)
    duplicate_removed_count = total_raw_rows - total_merged_rows
    duplicate_rate = calc_duplicate_rate(total_raw_rows, total_merged_rows)
    real_sold_rows = [row for row in rows if is_real_sold_row(row)]

    return {
        "total_raw_rows": str(total_raw_rows),
        "total_merged_rows": str(total_merged_rows),
        "duplicate_removed_count": str(duplicate_removed_count),
        "duplicate_rate": f"{duplicate_rate:.2%}",
        "urls_with_query": str(sum(row.get("url_query_removed") == "True" for row in rows)),
        "urls_cleaned": str(
            sum(row.get("product_url_original") != row.get("product_url_clean") for row in rows)
        ),
        "urls_with_src_module": str(
            sum("src_module" in row.get("product_url_original", "").lower() for row in rows)
        ),
        "urls_with_src_identifier": str(
            sum("src_identifier" in row.get("product_url_original", "").lower() for row in rows)
        ),
        "urls_with_src_tab_page_id": str(
            sum("src_tab_page_id" in row.get("product_url_original", "").lower() for row in rows)
        ),
        "urls_with_risk_marker": str(sum(row.get("has_risk_marker") == "True" for row in rows)),
        "product_id_mismatch_count": str(sum(row.get("product_id_match") != "True" for row in rows)),
        "clean_url_duplicate_count": str(count_clean_url_duplicates(rows)),
        "real_sold_rows": str(len(real_sold_rows)),
        "real_sold_urls_with_risk_marker": str(
            sum(row.get("has_risk_marker") == "True" for row in real_sold_rows)
        ),
    }


def save_csv(rows: list[dict[str, str]], output_file: Path, fieldnames: list[str]) -> None:
    """Save a UTF-8 BOM CSV for convenient Excel inspection."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def display_path(path: Path) -> str:
    """Return a stable project-relative path for terminal output."""
    return path.relative_to(PROJECT_ROOT).as_posix()


def main() -> None:
    """Run the V2.7B merge, deduplication, URL cleaning, and audit workflow."""
    all_rows: list[dict[str, str]] = []
    fieldname_groups: list[list[str]] = []

    for page_number, input_file in INPUT_FILES.items():
        rows, fieldnames = read_csv_rows(input_file, page_number)
        all_rows.extend(rows)
        fieldname_groups.append(fieldnames)

    output_fieldnames = merge_fieldnames(fieldname_groups)
    deduplicated_rows, product_id_counter, product_id_pages, first_rows = merge_and_deduplicate(all_rows)
    apply_url_cleaning(deduplicated_rows)
    duplicate_summary_rows = build_duplicate_summary_rows(
        product_id_counter,
        product_id_pages,
        first_rows,
    )
    audit_row = build_audit_row(len(all_rows), deduplicated_rows)

    save_csv(deduplicated_rows, MERGED_OUTPUT_FILE, output_fieldnames)
    save_csv([audit_row], AUDIT_OUTPUT_FILE, AUDIT_FIELDS)
    save_csv(duplicate_summary_rows, DUPLICATES_OUTPUT_FILE, DUPLICATE_SUMMARY_FIELDS)

    print("V2.7B 合并去重与 URL 清洗完成")
    print()
    print(f"原始总记录数：{audit_row['total_raw_rows']}")
    print(f"去重后商品数：{audit_row['total_merged_rows']}")
    print(f"删除重复数量：{audit_row['duplicate_removed_count']}")
    print(f"重复率：{audit_row['duplicate_rate']}")
    print(f"带 query 参数 URL 数：{audit_row['urls_with_query']}")
    print(f"已清洗 URL 数：{audit_row['urls_cleaned']}")
    print(f"疑似风险来源 URL 数：{audit_row['urls_with_risk_marker']}")
    print(f"真实 sold 商品数：{audit_row['real_sold_rows']}")
    print(f"真实 sold 中疑似风险来源 URL 数：{audit_row['real_sold_urls_with_risk_marker']}")
    print(f"product_id 不一致数量：{audit_row['product_id_mismatch_count']}")
    print(f"clean_url 重复数量：{audit_row['clean_url_duplicate_count']}")
    if audit_row["product_id_mismatch_count"] != "0":
        print("警告：存在 product_id 与 URL 中商品 ID 不一致的记录，请检查主表。")
    print()
    print("输出文件：")
    print(display_path(MERGED_OUTPUT_FILE))
    print(display_path(AUDIT_OUTPUT_FILE))
    print(display_path(DUPLICATES_OUTPUT_FILE))


if __name__ == "__main__":
    main()
