"""V2.9A：真实销量商品详情页单商品采集与 Description 属性解析脚本。

本阶段只从 V2.7 主表筛选 1 个 sales_tag 包含 sold 的真实销量商品，
使用 Scrapling StealthySession 打开详情页，并从 HTML 中真实解析 Description 全量属性。
"""

from __future__ import annotations

import csv
import html
import json
import math
import re
import sys
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
OUTPUT_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9a_one_sold_product_detail_attributes.csv"
DEBUG_DIR = PROJECT_ROOT / "data" / "debug" / "v2_9a_one_sold_product"
BROWSER_PROFILE_DIR = PROJECT_ROOT / "data" / "browser_profile" / "shein_sg"


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


def select_one_sold_product(products: list[dict[str, str]]) -> dict[str, str]:
    """筛选并选择 1 个真实销量强信号商品。"""
    candidates = [
        product
        for product in products
        if normalize_text(product.get("product_url"))
        and normalize_text(product.get("sales_tag"))
        and is_real_sales_tag(product.get("sales_tag"))
    ]
    if not candidates:
        raise RuntimeError("未找到 product_url 非空且 sales_tag 包含 sold 的候选商品")

    candidates.sort(
        key=lambda product: (
            -parse_int(product.get("appear_count")),
            -parse_sales_volume(product.get("sales_tag")),
            parse_int(product.get("product_id")) or 10**18,
        )
    )
    return candidates[0]


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


def build_raw_description_text(dom_text: str, attributes: dict[str, str], raw_snippet: str) -> str:
    """生成 Description 原始文本，便于人工核查。"""
    lines: list[str] = []
    if dom_text:
        lines.append("【Description DOM 文本】")
        lines.append(dom_text)
        lines.append("")
    if attributes:
        lines.append("【从 HTML 真实属性表提取的全部 key-value】")
        for key, value in attributes.items():
            lines.append(f"{key}: {value}")
        lines.append("")
    if raw_snippet:
        lines.append("【productDescriptionInfo 原始 HTML/JSON 片段】")
        lines.append(raw_snippet)
    return "\n".join(lines).strip()


def parse_description(html_text: str) -> tuple[dict[str, str], str, str]:
    """解析 Description 表格全部属性。"""
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        attributes = extract_description_attributes(html_text)
        dom_text = find_description_dom_text(soup)
        raw_snippet = find_product_description_snippet(html_text)
        raw_description_text = build_raw_description_text(dom_text, attributes, raw_snippet)
        if attributes:
            return attributes, raw_description_text, "success"
        return attributes, raw_description_text, "description_not_found"
    except Exception as exc:  # noqa: BLE001 - 单商品探测失败也要输出 CSV。
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


def write_output_csv(row: dict[str, str]) -> None:
    """写入单商品 CSV，使用 utf-8-sig 方便 Excel 打开。"""
    OUTPUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def fetch_and_parse_one_product(product: dict[str, str]) -> dict[str, str]:
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
        with StealthySession(
            real_chrome=True,
            headless=False,
            user_data_dir=str(BROWSER_PROFILE_DIR),
            retries=1,
            retry_delay=0,
        ) as session:
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
                "<head><meta charset=\"utf-8\"><title>V2.9A fetch failed</title></head>",
                "<body>",
                "<h1>V2.9A 商品详情页请求失败</h1>",
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
    write_output_csv(row)
    return row


def main() -> None:
    """执行 V2.9A 单商品详情页采集与 Description 解析。"""
    ensure_dirs()
    products = read_products()
    selected_product = select_one_sold_product(products)
    selected_product_id = normalize_text(selected_product.get("product_id"))

    print("V2.9A 真实销量商品详情页单商品采集")
    print("=" * 64)
    print(f"V2.7 商品总数：{len(products)}")
    print(f"选中 product_id：{selected_product_id}")
    print(f"appear_count：{selected_product.get('appear_count')}")
    print(f"sales_tag：{selected_product.get('sales_tag')}")
    print(f"product_url：{selected_product.get('product_url')}")

    row = fetch_and_parse_one_product(selected_product)
    extracted_count = sum(1 for field in KEY_FIELDS_FOR_STATS if row.get(field))

    print("\nV2.9A 单商品采集完成")
    print("=" * 64)
    print(f"product_id：{row['product_id']}")
    print(f"page_status：{row['page_status']}")
    print(f"status_reason：{row['status_reason']}")
    print(f"parse_status：{row['parse_status']}")
    print(f"属性总数：{row['attribute_count']}")
    print(f"关键字段提取数量：{extracted_count}/{len(KEY_FIELDS_FOR_STATS)}")
    print(f"CSV 保存路径：{OUTPUT_CSV_PATH}")
    print(f"HTML 保存路径：{row['html_saved_path']}")
    print(f"visible_text 保存路径：{row['visible_text_saved_path']}")
    print(f"Description 原始文本保存路径：{row['description_raw_text_saved_path']}")


if __name__ == "__main__":
    main()
