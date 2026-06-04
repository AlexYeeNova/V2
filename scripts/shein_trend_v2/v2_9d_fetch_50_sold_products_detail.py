"""V2.9D：真实 sold 商品详情页 50 个样本采集验证脚本。

本脚本基于 V2.9A 的单商品详情页采集与 Description 全量属性解析能力，
扩展到最多 50 个真实 sold 商品，用于验证不同商品 Description 字段不一致时，
解析逻辑是否稳定。
"""

from __future__ import annotations

import csv
import html
import json
import math
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


# 兼容项目本地 Scrapling 源码目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_SCRAPLING_DIR = PROJECT_ROOT / "Scrapling"
if LOCAL_SCRAPLING_DIR.exists():
    sys.path.insert(0, str(LOCAL_SCRAPLING_DIR))

from scrapling.fetchers import StealthySession  # noqa: E402


INPUT_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_7_products_10_pages_merged.csv"
OUTPUT_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d_50_sold_products_detail_attributes.csv"
SUMMARY_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d_50_sold_products_detail_summary.csv"
DEBUG_DIR = PROJECT_ROOT / "data" / "debug" / "v2_9d_50_sold_products"
BROWSER_PROFILE_DIR = PROJECT_ROOT / "data" / "browser_profile" / "shein_sg"
MAX_PRODUCTS = 50
V29C_REFERENCE_SUCCESS_RATE = 0.95


CONNECTION_CLOSED_KEYWORDS = [
    "ERR_CONNECTION_CLOSED",
    "unexpectedly closed the connection",
    "This site can't be reached",
    "site can't be reached",
]

STRONG_BLOCK_KEYWORDS = [
    "OOPS",
    "too many requests",
    "exceeds our limit",
    "captcha",
    "challenge",
    "access denied",
    "forbidden",
]

UNAVAILABLE_KEYWORDS = [
    "404",
    "Page Not Found",
    "product not found",
    "item not found",
    "unavailable",
    "no longer available",
    "removed",
]


# 已知 Description 属性到 CSV 固定字段的映射。
# Care Instructions 不映射为独立字段，只保留在 attributes_json 和 raw_description_text。
ATTRIBUTE_FIELD_MAP = {
    "Color": "color",
    "Material": "material",
    "Composition": "composition",
    "Fabric Elasticity": "fabric_elasticity",
    "Fit Type": "fit_type",
    "Pattern Type": "pattern_type",
    "Style": "style",
    "Occasion": "occasion",
    "Details": "details",
    "Type": "type",
    "Length": "length",
    "Neckline": "neckline",
    "Sleeve Length": "sleeve_length",
    "Sleeve Type": "sleeve_type",
    "Waist Line": "waist_line",
    "Closure Type": "closure_type",
    "Placket": "placket",
    "Pockets": "pockets",
    "Body": "body",
    "Hem Shaped": "hem_shaped",
    "Lined For Added Warmth": "lined_for_added_warmth",
    "Features": "features",
    "Sheer": "sheer",
    "Temperature": "temperature",
    "Festivals": "festivals",
}


CSV_FIELDS = [
    "product_id",
    "product_url",
    "final_url",
    "source_page",
    "appear_count",
    "appear_pages",
    "sales_tag",
    "is_real_sales_tag",
    "title",
    "price",
    "sku",
    "color",
    "material",
    "composition",
    "fabric_elasticity",
    "fit_type",
    "pattern_type",
    "style",
    "occasion",
    "details",
    "type",
    "length",
    "neckline",
    "sleeve_length",
    "sleeve_type",
    "waist_line",
    "closure_type",
    "placket",
    "pockets",
    "body",
    "hem_shaped",
    "lined_for_added_warmth",
    "features",
    "sheer",
    "temperature",
    "festivals",
    "attribute_count",
    "attribute_keys",
    "attributes_json",
    "raw_description_text",
    "crawl_time",
    "page_status",
    "status_reason",
    "parse_status",
    "html_saved_path",
    "visible_text_saved_path",
    "description_raw_text_saved_path",
]


SUMMARY_FIELDS = [
    "total_planned",
    "total_output_rows",
    "page_success_count",
    "parse_success_count",
    "blocked_or_verify_count",
    "connection_closed_count",
    "timeout_count",
    "fetch_failed_count",
    "product_unavailable_count",
    "not_found_count",
    "average_attribute_count",
    "max_attribute_count",
    "min_attribute_count",
    "average_success_attribute_count",
    "max_success_attribute_count",
    "min_success_attribute_count",
    "success_rate",
    "parse_success_rate",
    "crawl_time",
]


KEY_FIELDS_FOR_STATS = [
    "sku",
    "color",
    "material",
    "composition",
    "fabric_elasticity",
    "fit_type",
    "pattern_type",
    "style",
    "occasion",
    "details",
    "type",
    "length",
]


def ensure_dirs() -> None:
    """自动创建输出目录、调试目录和浏览器持久化目录。"""
    OUTPUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def normalize_text(value: Any) -> str:
    """安全转字符串并去除首尾空白，兼容 None 和 NaN。"""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_int(value: Any) -> int:
    """安全解析整数。"""
    try:
        return int(float(normalize_text(value)))
    except ValueError:
        return 0


def is_real_sales_tag(sales_tag: Any) -> bool:
    """只有 sales_tag 小写后包含 sold，才算真实销量标签。"""
    return "sold" in normalize_text(sales_tag).lower()


def parse_sales_volume(sales_tag: Any) -> int:
    """从 34.1k+ sold、805 sold 等文本中解析销量数字，用于排序。"""
    text = normalize_text(sales_tag).lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*([km]?)\s*\+?\s*sold", text)
    if not match:
        return 0
    amount = float(match.group(1))
    unit = match.group(2)
    if unit == "k":
        amount *= 1000
    elif unit == "m":
        amount *= 1_000_000
    return int(amount)


def extract_product_id_from_url(product_url: str) -> str:
    """从商品 URL 中解析 product_id。"""
    match = re.search(r"-p-(\d+)\.html", product_url or "")
    return match.group(1) if match else ""


def read_products() -> list[dict[str, str]]:
    """读取 V2.7 主数据集。"""
    if not INPUT_CSV_PATH.exists():
        raise FileNotFoundError(f"输入文件不存在：{INPUT_CSV_PATH}")
    with INPUT_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def select_sold_products(products: list[dict[str, str]]) -> list[dict[str, str]]:
    """筛选并选择最多 50 个真实 sold 商品。"""
    candidates = [
        product
        for product in products
        if normalize_text(product.get("product_url"))
        and normalize_text(product.get("sales_tag"))
        and is_real_sales_tag(product.get("sales_tag"))
    ]
    candidates.sort(
        key=lambda product: (
            -parse_int(product.get("appear_count")),
            -parse_sales_volume(product.get("sales_tag")),
            parse_int(product.get("product_id")) or 10**18,
        )
    )
    return candidates[:MAX_PRODUCTS]


def decode_json_fragment(value: str) -> str:
    """解码 HTML 实体和 JSON 字符串转义。"""
    value = html.unescape(value)
    try:
        value = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        pass
    return normalize_text(value)


def scroll_detail_page(browser_page: Any) -> None:
    """轻量滚动详情页，触发折叠区和下方内容加载。"""
    browser_page.wait_for_timeout(3000)
    for _ in range(3):
        browser_page.mouse.wheel(0, 1000)
        browser_page.wait_for_timeout(1000)


def fetch_detail_page(session: StealthySession, product_url: str) -> Any:
    """使用真实 Chrome 和持久化目录访问详情页。"""
    return session.fetch(
        product_url,
        network_idle=True,
        wait=3000,
        timeout=90000,
        locale="en-SG",
        timezone_id="Asia/Singapore",
        page_action=scroll_detail_page,
    )


def get_html_content(page: Any) -> str:
    """读取完整 HTML。"""
    return str(page.html_content)


def get_visible_text(page: Any) -> str:
    """读取页面可见文本。"""
    return normalize_text(page.get_all_text(" ", strip=True))


def get_final_url(page: Any, fallback_url: str) -> str:
    """尽量读取最终 URL。"""
    for attr_name in ("url", "final_url"):
        value = getattr(page, attr_name, "")
        if value:
            return str(value)
    return fallback_url


def extract_sku(soup: BeautifulSoup, html_text: str) -> str:
    """从页面文本或 HTML 数据中提取 SKU。"""
    visible_text = soup.get_text(" ", strip=True)
    patterns = [
        r"SKU:\s*([A-Za-z0-9_-]+)",
        r"ecomm_prodid%3D([A-Za-z0-9_-]+)",
        r'"goods_sn"\s*:\s*"([^"]+)"',
        r'"sku_code"\s*:\s*"([^"]+)"',
    ]
    for source_text in (visible_text, html_text):
        for pattern in patterns:
            match = re.search(pattern, source_text, re.IGNORECASE)
            if match:
                return decode_json_fragment(match.group(1))
    return ""


def extract_title(soup: BeautifulSoup, html_text: str) -> str:
    """优先从页面 H1 或商品数据中提取标题。"""
    for node in soup.find_all("h1"):
        text = normalize_text(node.get_text(" ", strip=True))
        if text and "shipping to" not in text.lower():
            return text
    match = re.search(r'"goods_name"\s*:\s*"([^"]+)"', html_text)
    if match:
        return decode_json_fragment(match.group(1))
    if soup.title:
        return normalize_text(soup.title.get_text(" ", strip=True).replace("| SHEIN Singapore", ""))
    return ""


def extract_price(soup: BeautifulSoup, html_text: str, visible_text: str) -> str:
    """优先提取详情页主价格，其次从商品数据中读取 salePrice。"""
    price_node = soup.find(attrs={"aria-label": re.compile(r"^S\$\d", re.I)})
    if price_node:
        price_text = normalize_text(price_node.get("aria-label", ""))
        if price_text:
            return price_text

    patterns = [
        r'"salePrice"\s*:\s*\{[^{}]*?"amountWithSymbol"\s*:\s*"([^"]+)"',
        r"S\$\s*\d+(?:\.\d{1,2})?",
    ]
    for source_text in (html_text, visible_text):
        for pattern in patterns:
            match = re.search(pattern, source_text, re.IGNORECASE | re.DOTALL)
            if match:
                return decode_json_fragment(match.group(1) if match.lastindex else match.group(0))
    return ""


def count_product_body_signals(html_text: str, visible_text: str) -> int:
    """统计商品主体信息命中数量，至少命中 2 项即优先认为成功。"""
    soup = BeautifulSoup(html_text, "html.parser")
    combined_text = f"{visible_text} {soup.get_text(' ', strip=True)} {html_text}".lower()

    signals = 0
    if extract_sku(soup, html_text):
        signals += 1
    if extract_price(soup, html_text, visible_text):
        signals += 1
    if "add to cart" in combined_text:
        signals += 1
    if "size guide" in combined_text or "size & fit" in combined_text:
        signals += 1
    if "description" in combined_text or "productdescriptioninfo" in combined_text:
        signals += 1
    if re.search(r"\bcolor\b", combined_text):
        signals += 1
    if re.search(r"\bsize\b", combined_text):
        signals += 1
    return signals


def contains_any(text: str, keywords: list[str]) -> bool:
    """判断文本中是否包含任一关键词。"""
    lower_text = text.lower()
    return any(keyword.lower() in lower_text for keyword in keywords)


def detect_page_status(
    html_text: str,
    visible_text: str,
    error_text: str,
    final_url: str,
    product_id: str,
    product_url: str,
) -> tuple[str, str]:
    """综合页面主体信息、异常信息和关键词判断页面状态。"""
    combined_text = f"{html_text} {visible_text} {error_text}"

    if error_text:
        if contains_any(combined_text, CONNECTION_CLOSED_KEYWORDS):
            return "connection_closed", "页面或异常信息显示连接被关闭"
        if "timeout" in error_text.lower():
            return "timeout", "页面请求超时"
        return "fetch_failed", error_text[:300]

    body_signal_count = count_product_body_signals(html_text, visible_text) if html_text else 0
    if body_signal_count >= 2:
        return "success", f"商品主体信息命中 {body_signal_count} 项"
    if contains_any(combined_text, CONNECTION_CLOSED_KEYWORDS):
        return "connection_closed", "页面或异常信息显示连接被关闭"
    if contains_any(combined_text, UNAVAILABLE_KEYWORDS):
        if "404" in combined_text or "page not found" in combined_text.lower():
            return "not_found", "页面显示 404 或 Page Not Found"
        return "product_unavailable", "页面显示商品不可用或已下架"
    if contains_any(combined_text, STRONG_BLOCK_KEYWORDS):
        return "blocked_or_verify", "商品主体信息不足且出现强风控词"
    if final_url and final_url != product_url and product_id and product_id not in final_url:
        return "redirected", "最终 URL 与目标商品不一致"
    return "fetch_failed", "未获取到足够商品主体信息"


def find_description_dom_text(soup: BeautifulSoup) -> str:
    """提取 Description 折叠模块中的 DOM 文本摘要。"""
    section = soup.find("section", attrs={"aria-label": re.compile(r"Description", re.I)})
    if section:
        return section.get_text("\n", strip=True)
    title_node = soup.find(string=re.compile(r"^\s*Description\s*$", re.I))
    if not title_node:
        return ""
    container = title_node.parent
    for _ in range(4):
        if container and container.parent:
            container = container.parent
    return container.get_text("\n", strip=True) if container else ""


def find_product_description_snippet(html_text: str) -> str:
    """截取 productDescriptionInfo 附近原始片段，方便人工核查。"""
    marker_index = html_text.find('"productDescriptionInfo"')
    if marker_index < 0:
        marker_index = html_text.find("productDescriptionInfo")
    if marker_index < 0:
        return ""
    start = max(0, marker_index - 300)
    end = min(len(html_text), marker_index + 18000)
    return html.unescape(html_text[start:end])


def extract_description_attributes(html_text: str) -> dict[str, str]:
    """从 HTML 中提取 Description 的全部真实 key-value 属性。"""
    attributes: dict[str, str] = {}

    pair_pattern = re.compile(
        r'"attr_name"\s*:\s*"(?P<key>[^"]+)"'
        r'.{0,500}?'
        r'"attr_value"\s*:\s*"(?P<value>[^"]*)"',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pair_pattern.finditer(html_text):
        key = decode_json_fragment(match.group("key"))
        value = decode_json_fragment(match.group("value"))
        if key and value and key not in attributes:
            attributes[key] = value

    camel_pair_pattern = re.compile(
        r'"attrName"\s*:\s*"(?P<key>[^"]+)"'
        r'.{0,300}?'
        r'"attrValue"\s*:\s*"(?P<value>[^"]*)"',
        re.IGNORECASE | re.DOTALL,
    )
    for match in camel_pair_pattern.finditer(html_text):
        key = decode_json_fragment(match.group("key"))
        value = decode_json_fragment(match.group("value"))
        if key and value and key not in attributes:
            attributes[key] = value
    return attributes


def build_clean_description_text(attributes: dict[str, str]) -> str:
    """由已解析出的 Description 属性反向生成干净 key-value 文本。"""
    return "\n".join(f"{key}: {value}" for key, value in attributes.items()).strip()


def parse_description(html_text: str) -> tuple[dict[str, str], str, str]:
    """解析 Description 表格全部属性。"""
    try:
        attributes = extract_description_attributes(html_text)
        raw_description_text = build_clean_description_text(attributes)
        if attributes:
            return attributes, raw_description_text, "success"
        return attributes, raw_description_text, "description_not_found"
    except Exception as exc:  # noqa: BLE001 - 单商品失败不能中断整批。
        return {}, f"解析 Description 失败：{type(exc).__name__}: {exc}", "parse_failed"


def save_text_file(path: Path, content: str) -> None:
    """保存 UTF-8 文本或 HTML 调试文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_base_row(product: dict[str, str], paths: dict[str, Path]) -> dict[str, str]:
    """构造默认输出行，确保失败时也能写出完整 CSV。"""
    product_url = normalize_text(product.get("product_url"))
    product_id = normalize_text(product.get("product_id")) or extract_product_id_from_url(product_url)
    row = {field: "" for field in CSV_FIELDS}
    row.update(
        {
            "product_id": product_id,
            "product_url": product_url,
            "final_url": product_url,
            "source_page": normalize_text(product.get("source_page")),
            "appear_count": normalize_text(product.get("appear_count")),
            "appear_pages": normalize_text(product.get("appear_pages")),
            "sales_tag": normalize_text(product.get("sales_tag")),
            "is_real_sales_tag": str(is_real_sales_tag(product.get("sales_tag"))).upper(),
            "title": normalize_text(product.get("title")),
            "price": normalize_text(product.get("price")),
            "crawl_time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "page_status": "fetch_failed",
            "status_reason": "",
            "parse_status": "skipped_due_to_page_status",
            "attribute_count": "0",
            "html_saved_path": str(paths["html"]),
            "visible_text_saved_path": str(paths["visible_text"]),
            "description_raw_text_saved_path": str(paths["description_raw_text"]),
        }
    )
    return row


def apply_attributes_to_row(row: dict[str, str], attributes: dict[str, str]) -> None:
    """把全量属性写入 JSON 字段，并把已知属性映射到固定列。"""
    for original_key, field_name in ATTRIBUTE_FIELD_MAP.items():
        row[field_name] = attributes.get(original_key, "")

    row["attribute_count"] = str(len(attributes))
    row["attribute_keys"] = ",".join(attributes.keys())
    row["attributes_json"] = json.dumps(attributes, ensure_ascii=False, sort_keys=False)


def write_output_csv(rows: list[dict[str, str]]) -> None:
    """写入批量 CSV，使用 utf-8-sig 方便 Excel 打开。"""
    OUTPUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def calc_rate(count: int, total: int) -> str:
    """计算百分比字符串。"""
    if total <= 0:
        return "0.00%"
    return f"{count / total:.2%}"


def build_summary_row(total_planned: int, rows: list[dict[str, str]]) -> dict[str, str]:
    """生成 V2.9D 采集结果汇总行。"""
    attribute_counts = [parse_int(row.get("attribute_count")) for row in rows]
    success_attribute_counts = [
        parse_int(row.get("attribute_count"))
        for row in rows
        if row.get("page_status") == "success" and row.get("parse_status") == "success"
    ]
    total_output_rows = len(rows)
    page_success_count = sum(1 for row in rows if row.get("page_status") == "success")
    parse_success_count = sum(1 for row in rows if row.get("parse_status") == "success")
    return {
        "total_planned": str(total_planned),
        "total_output_rows": str(total_output_rows),
        "page_success_count": str(page_success_count),
        "parse_success_count": str(parse_success_count),
        "blocked_or_verify_count": str(sum(1 for row in rows if row.get("page_status") == "blocked_or_verify")),
        "connection_closed_count": str(sum(1 for row in rows if row.get("page_status") == "connection_closed")),
        "timeout_count": str(sum(1 for row in rows if row.get("page_status") == "timeout")),
        "fetch_failed_count": str(sum(1 for row in rows if row.get("page_status") == "fetch_failed")),
        "product_unavailable_count": str(sum(1 for row in rows if row.get("page_status") == "product_unavailable")),
        "not_found_count": str(sum(1 for row in rows if row.get("page_status") == "not_found")),
        "average_attribute_count": f"{sum(attribute_counts) / len(attribute_counts):.2f}" if attribute_counts else "0.00",
        "max_attribute_count": str(max(attribute_counts)) if attribute_counts else "0",
        "min_attribute_count": str(min(attribute_counts)) if attribute_counts else "0",
        "average_success_attribute_count": (
            f"{sum(success_attribute_counts) / len(success_attribute_counts):.2f}"
            if success_attribute_counts
            else "0.00"
        ),
        "max_success_attribute_count": str(max(success_attribute_counts)) if success_attribute_counts else "0",
        "min_success_attribute_count": str(min(success_attribute_counts)) if success_attribute_counts else "0",
        "success_rate": calc_rate(page_success_count, total_output_rows),
        "parse_success_rate": calc_rate(parse_success_count, total_output_rows),
        "crawl_time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def write_summary_csv(total_planned: int, rows: list[dict[str, str]]) -> dict[str, str]:
    """写入 V2.9D 汇总 CSV，并返回汇总行。"""
    summary_row = build_summary_row(total_planned, rows)
    SUMMARY_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerow(summary_row)
    return summary_row


def fetch_and_parse_one_product(session: StealthySession, product: dict[str, str]) -> dict[str, str]:
    """在线采集 1 个真实销量商品详情页并解析 Description。"""
    product_url = normalize_text(product.get("product_url"))
    product_id = normalize_text(product.get("product_id")) or extract_product_id_from_url(product_url)
    paths = {
        "html": DEBUG_DIR / f"{product_id}.html",
        "visible_text": DEBUG_DIR / f"{product_id}_visible_text.txt",
        "description_raw_text": DEBUG_DIR / f"{product_id}_description_raw_text.txt",
    }
    row = build_base_row(product, paths)

    html_text = ""
    visible_text = ""
    error_text = ""

    try:
        page = fetch_detail_page(session, product_url)
        html_text = get_html_content(page)
        visible_text = get_visible_text(page)
        row["final_url"] = get_final_url(page, product_url)
    except Exception as exc:  # noqa: BLE001 - 失败也要保存调试文件和 CSV。
        error_text = f"{type(exc).__name__}: {exc}"
        visible_text = error_text
        html_text = "\n".join(
            [
                "<!doctype html>",
                "<html>",
                "<head><meta charset=\"utf-8\"><title>V2.9D fetch failed</title></head>",
                "<body>",
                "<h1>V2.9D 商品详情页请求失败</h1>",
                f"<p>product_id：{html.escape(product_id)}</p>",
                f"<p>目标 URL：{html.escape(product_url)}</p>",
                f"<pre>{html.escape(error_text)}</pre>",
                "</body>",
                "</html>",
            ]
        )

    save_text_file(paths["html"], html_text)
    save_text_file(paths["visible_text"], visible_text)

    page_status, status_reason = detect_page_status(
        html_text=html_text,
        visible_text=visible_text,
        error_text=error_text,
        final_url=row["final_url"],
        product_id=product_id,
        product_url=product_url,
    )
    row["page_status"] = page_status
    row["status_reason"] = status_reason

    soup = BeautifulSoup(html_text, "html.parser")
    if page_status == "success":
        row["sku"] = extract_sku(soup, html_text)
        row["title"] = extract_title(soup, html_text) or row["title"]
        row["price"] = extract_price(soup, html_text, visible_text) or row["price"]
        attributes, raw_description_text, parse_status = parse_description(html_text)
        row["parse_status"] = parse_status
        row["raw_description_text"] = raw_description_text
        apply_attributes_to_row(row, attributes)
    else:
        row["parse_status"] = "skipped_due_to_page_status"
        row["raw_description_text"] = f"页面状态为 {page_status}，跳过 Description 解析：{status_reason}"

    save_text_file(paths["description_raw_text"], row["raw_description_text"])
    return row


def print_product_result(row: dict[str, str]) -> None:
    """输出单个商品采集结果。"""
    key_count = sum(1 for field in KEY_FIELDS_FOR_STATS if row.get(field))
    print(
        f"完成 product_id={row['product_id']}，"
        f"page_status={row['page_status']}，"
        f"parse_status={row['parse_status']}，"
        f"attribute_count={row['attribute_count']}，"
        f"关键字段={key_count}/{len(KEY_FIELDS_FOR_STATS)}"
    )


def main() -> None:
    """执行 V2.9D 50 个真实 sold 商品详情页采集验证。"""
    ensure_dirs()
    products = read_products()
    sold_candidates = [
        product
        for product in products
        if normalize_text(product.get("product_url"))
        and normalize_text(product.get("sales_tag"))
        and is_real_sales_tag(product.get("sales_tag"))
    ]
    selected_products = select_sold_products(products)

    print("V2.9D 真实 sold 商品详情页 50 个样本采集验证")
    print("=" * 64)
    print(f"候选真实 sold 商品数量：{len(sold_candidates)}")
    print(f"本次计划采集商品数：{len(selected_products)}")
    for index, product in enumerate(selected_products, start=1):
        print(
            f"待采集 {index}/{len(selected_products)}："
            f"product_id={product.get('product_id')}，"
            f"appear_count={product.get('appear_count')}，"
            f"sales_tag={product.get('sales_tag')}"
        )

    results: list[dict[str, str]] = []
    with StealthySession(
        real_chrome=True,
        headless=False,
        user_data_dir=str(BROWSER_PROFILE_DIR),
        retries=1,
        retry_delay=0,
    ) as session:
        for index, product in enumerate(selected_products, start=1):
            product_id = normalize_text(product.get("product_id")) or extract_product_id_from_url(
                normalize_text(product.get("product_url"))
            )
            print(f"\n开始采集 {index}/{len(selected_products)}：product_id={product_id}")
            row = fetch_and_parse_one_product(session, product)
            results.append(row)
            write_output_csv(results)
            print_product_result(row)

            if index < len(selected_products):
                sleep_seconds = random.randint(10, 20)
                print(f"等待 {sleep_seconds} 秒后继续下一个商品...")
                time.sleep(sleep_seconds)

    write_output_csv(results)
    success_count = sum(1 for row in results if row["page_status"] == "success")
    parse_success_count = sum(1 for row in results if row["parse_status"] == "success")
    summary_row = write_summary_csv(len(selected_products), results)

    print("\nV2.9D 50 个样本详情采集完成")
    print("=" * 64)
    print(f"候选真实 sold 商品数量：{len(sold_candidates)}")
    print(f"本次计划采集商品数：{len(selected_products)}")
    print(f"page_status = success 数量：{success_count}")
    print(f"parse_status = success 数量：{parse_success_count}")
    print(f"blocked_or_verify count: {summary_row['blocked_or_verify_count']}")
    print(f"connection_closed count: {summary_row['connection_closed_count']}")
    print(f"timeout count: {summary_row['timeout_count']}")
    print(f"fetch_failed count: {summary_row['fetch_failed_count']}")
    print(f"product_unavailable count: {summary_row['product_unavailable_count']}")
    print(f"not_found count: {summary_row['not_found_count']}")
    if selected_products:
        success_rate_value = success_count / len(selected_products)
        if success_rate_value < V29C_REFERENCE_SUCCESS_RATE - 0.05:
            print("提示：本次 success_rate 明显低于 V2.9C 参考值，可能存在网络波动或访问节奏压力问题。")
    for row in results:
        key_count = sum(1 for field in KEY_FIELDS_FOR_STATS if row.get(field))
        print(
            f"product_id={row['product_id']}，"
            f"attribute_count={row['attribute_count']}，"
            f"关键字段={key_count}/{len(KEY_FIELDS_FOR_STATS)}"
        )
    print(f"CSV 保存路径：{OUTPUT_CSV_PATH}")
    print(f"Debug 目录：{DEBUG_DIR}")

    print(f"Summary CSV path: {SUMMARY_CSV_PATH}")


if __name__ == "__main__":
    main()
