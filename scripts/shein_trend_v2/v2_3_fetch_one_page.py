"""V2.3：使用真实 Chrome Profile 采集 SHEIN 女装类目指定页。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any
from urllib.parse import urljoin


# 将本地 Scrapling 源码目录加入导入路径，方便在未安装包时直接运行本仓库脚本。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_SCRAPLING_DIR = PROJECT_ROOT / "Scrapling"
if LOCAL_SCRAPLING_DIR.exists():
    sys.path.insert(0, str(LOCAL_SCRAPLING_DIR))

from scrapling.fetchers import StealthySession  # noqa: E402


# 目标类目页与输出文件路径。
TARGET_URL = "https://sg.shein.com/Women-Clothing-c-2030.html"
DEBUG_HTML_PATH = PROJECT_ROOT / "data" / "debug" / "v2_3_page_1.html"
CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_3_products_page_1.csv"
BROWSER_PROFILE_DIR = PROJECT_ROOT / "data" / "browser_profile" / "shein_sg"
CSV_FIELDS = [
    "title",
    "price",
    "product_url",
    "image_url",
    "crawl_time",
    "original_price",
    "discount",
    "rating",
    "review_count",
    "sales_tag",
]
ENHANCED_FIELDS = ["original_price", "discount", "rating", "review_count", "sales_tag"]
CHALLENGE_URL_KEYWORDS = ["risk", "challenge"]
CHALLENGE_TEXT_KEYWORDS = [
    "challenge",
    "security check",
    "access denied",
    "blocked",
    "captcha",
    "risk control",
    "unusual activity",
    "too many requests",
]
VERIFICATION_TEXT_KEYWORDS = [
    "verify",
    "verification",
    "robot",
    "human",
    "not a robot",
    "click the icon",
    "click icon",
    "icon verification",
    "please click",
    "press and hold",
    "drag",
    "slider",
    "complete the verification",
    "confirm you are human",
]
RESULT_SUGGESTIONS = {
    "normal_page": "可作为有效样本",
    "verification_suspected": "可作为部分样本，但需记录验证干扰",
    "challenge_page": "不建议作为有效样本",
}


def scroll_first_page(browser_page: Any) -> None:
    """轻量滚动页面，触发首屏下方商品懒加载。"""
    browser_page.wait_for_timeout(2000)
    for _ in range(4):
        browser_page.mouse.wheel(0, 1200)
        browser_page.wait_for_timeout(800)


def normalize_text(value: Any) -> str:
    """清理文本中的换行和多余空白。"""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def first_text(selector: Any, css_selectors: list[str]) -> str:
    """按多个 CSS 选择器依次读取第一个非空文本。"""
    for css_selector in css_selectors:
        value = selector.css(css_selector).get()
        cleaned = normalize_text(value)
        if cleaned:
            return cleaned
    return ""


def first_attr(selector: Any, css_selectors: list[str], attr_names: list[str]) -> str:
    """按多个 CSS 选择器和属性名依次读取第一个非空属性值。"""
    for css_selector in css_selectors:
        for element in selector.css(css_selector):
            for attr_name in attr_names:
                value = normalize_text(element.attrib.get(attr_name))
                if value:
                    return value
    return ""


def normalize_url(value: str, base_url: str) -> str:
    """补全商品或图片 URL。"""
    if not value:
        return ""
    if value.startswith("//"):
        return f"https:{value}"
    return urljoin(base_url, value)


def extract_price_from_text(text: str) -> str:
    """从商品卡片文本中提取价格。"""
    match = re.search(r"(?:S\$|SGD|\$)\s*\d+(?:[.,]\d{1,2})?", text, re.IGNORECASE)
    return match.group(0).strip() if match else ""


def extract_original_price(card: Any, sale_price: str) -> str:
    """从商品卡片中尝试提取原价。"""
    original_price = first_text(
        card,
        [
            ".goods-price__retail::text",
            ".goods-price__original::text",
            ".product-card__retail-price::text",
            ".product-card__original-price::text",
            ".S-product-item__retail-price::text",
            "del::text",
            "s::text",
            "[class*='retail']::text",
            "[class*='original']::text",
            "[class*='line-through']::text",
        ],
    )
    if original_price:
        return original_price

    prices = re.findall(r"(?:S\$|SGD|\$)\s*\d+(?:[.,]\d{1,2})?", normalize_text(card.get_all_text(" ", strip=True)), re.IGNORECASE)
    for price in prices:
        cleaned_price = normalize_text(price)
        if cleaned_price and cleaned_price != sale_price:
            return cleaned_price
    return ""


def extract_discount(card: Any) -> str:
    """从商品卡片中尝试提取折扣信息。"""
    discount = first_text(
        card,
        [
            ".discount-label::text",
            ".goods-discount::text",
            ".product-card__discount::text",
            ".S-product-item__discount::text",
            "[class*='discount']::text",
            "[class*='off']::text",
        ],
    )
    if discount:
        return discount

    card_text = normalize_text(card.get_all_text(" ", strip=True))
    match = re.search(r"(?:-\s*)?\d{1,2}%\s*(?:off)?", card_text, re.IGNORECASE)
    return match.group(0).strip() if match else ""


def extract_rating(card: Any) -> str:
    """从商品卡片中尝试提取评分。"""
    rating = first_text(
        card,
        [
            "[class*='rating']::text",
            "[class*='rate']::text",
            "[class*='star']::text",
            "[aria-label*='rating']::text",
            "[aria-label*='Rating']::text",
        ],
    )
    if rating:
        return rating

    rating_attr = first_attr(
        card,
        ["[aria-label*='rating']", "[aria-label*='Rating']", "[class*='rating']", "[class*='star']"],
        ["aria-label", "title", "data-rating", "data-rate"],
    )
    match = re.search(r"\d(?:\.\d)?", rating_attr)
    return match.group(0) if match else ""


def extract_review_count(card: Any) -> str:
    """从商品卡片中尝试提取评论数量。"""
    review_count = first_text(
        card,
        [
            "[class*='review']::text",
            "[class*='comment']::text",
            "[class*='rating-count']::text",
            "[class*='reviews']::text",
        ],
    )
    if review_count:
        return review_count

    card_text = normalize_text(card.get_all_text(" ", strip=True))
    match = re.search(r"\(?\s*[\d,.]+[Kk]?\s*(?:reviews?|comments?)\s*\)?", card_text, re.IGNORECASE)
    if match:
        return match.group(0).strip()
    match = re.search(r"\(\s*[\d,.]+[Kk]?\s*\)", card_text)
    return match.group(0).strip("() ") if match else ""


def extract_sales_tag(card: Any) -> str:
    """从商品卡片中尝试提取销量或营销标签。"""
    sales_tag = first_text(
        card,
        [
            ".goods-label::text",
            ".product-card__selling-proposition::text",
            ".product-card__sales-label::text",
            ".S-product-item__sales-label::text",
            "[class*='sales']::text",
            "[class*='sold']::text",
            "[class*='label']::text",
            "[class*='tag']::text",
            "[class*='badge']::text",
        ],
    )
    if sales_tag:
        return sales_tag

    card_text = normalize_text(card.get_all_text(" ", strip=True))
    match = re.search(r"[\d,.]+[Kk]?\+?\s*(?:sold|viewed|added|claimed)", card_text, re.IGNORECASE)
    return match.group(0).strip() if match else ""


def extract_enhanced_fields_from_card(card: Any, price: str) -> dict[str, str]:
    """从商品卡片中统一提取 V2.2 新增字段。"""
    return {
        "original_price": extract_original_price(card, price),
        "discount": extract_discount(card),
        "rating": extract_rating(card),
        "review_count": extract_review_count(card),
        "sales_tag": extract_sales_tag(card),
    }


def contains_any_keyword(text: str, keywords: list[str]) -> bool:
    """判断文本中是否包含任一关键词。"""
    lowered_text = text.lower()
    return any(keyword in lowered_text for keyword in keywords)


def collect_status_signals(page: Any) -> dict[str, bool]:
    """收集页面状态识别信号。"""
    current_url = normalize_text(page.url)
    page_text = normalize_text(page.get_all_text(" ", strip=True))
    html_text = normalize_text(page.html_content)
    combined_text = f"{page_text} {html_text}"

    return {
        "url_contains_risk_or_challenge": contains_any_keyword(current_url, CHALLENGE_URL_KEYWORDS),
        "text_contains_verification_prompt": contains_any_keyword(page_text, VERIFICATION_TEXT_KEYWORDS),
        "text_contains_icon_click_verification": contains_any_keyword(
            combined_text,
            ["click the icon", "click icon", "icon verification", "select the icon", "tap the icon"],
        ),
        "text_contains_robot_human_verify_challenge": contains_any_keyword(
            page_text,
            ["robot", "human", "verify", "verification", "challenge"],
        ),
        "text_contains_challenge_prompt": contains_any_keyword(page_text, CHALLENGE_TEXT_KEYWORDS),
    }


def judge_page_status(page: Any, product_count: int) -> tuple[str, str, dict[str, bool]]:
    """根据 URL、页面文本和商品数量判断页面状态，并给出结果建议。"""
    signals = collect_status_signals(page)

    if signals["url_contains_risk_or_challenge"] or (
        product_count <= 0 and signals["text_contains_challenge_prompt"]
    ):
        status = "challenge_page"
    elif (
        signals["text_contains_challenge_prompt"]
        or signals["text_contains_verification_prompt"]
        or signals["text_contains_icon_click_verification"]
        or signals["text_contains_robot_human_verify_challenge"]
    ):
        status = "verification_suspected"
    elif product_count <= 0 and (
        signals["text_contains_verification_prompt"]
        or signals["text_contains_robot_human_verify_challenge"]
    ):
        status = "verification_suspected"
    else:
        status = "normal_page"

    return status, RESULT_SUGGESTIONS[status], signals


def find_product_card(anchor: Any) -> Any:
    """从商品链接向上寻找更像商品卡片的父级节点。"""
    for ancestor in anchor.iterancestors():
        ancestor_text = normalize_text(ancestor.get_all_text(" ", strip=True))
        has_price = bool(extract_price_from_text(ancestor_text))
        has_image = bool(ancestor.css("img"))
        if has_price and has_image:
            return ancestor
    return anchor.parent or anchor


def extract_products_from_dom(page: Any, crawl_time: str) -> list[dict[str, str]]:
    """从渲染后的 DOM 中提取商品基础信息。"""
    products: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    # SHEIN 商品详情链接通常包含 -p-，优先以链接为入口定位商品卡片。
    product_links = page.css("a[href*='-p-'], a[href*='/p-']")
    for link in product_links:
        product_url = normalize_url(normalize_text(link.attrib.get("href")), page.url)
        if not product_url or product_url in seen_urls:
            continue

        card = find_product_card(link)
        card_text = normalize_text(card.get_all_text(" ", strip=True))
        title = (
            normalize_text(link.attrib.get("title"))
            or normalize_text(link.attrib.get("aria-label"))
            or first_text(
                card,
                [
                    ".goods-title-link::text",
                    ".product-card__goods-title::text",
                    ".S-product-item__name::text",
                    "[class*='title']::text",
                    "[class*='name']::text",
                ],
            )
            or normalize_text(link.get_all_text(" ", strip=True))
        )
        price = first_text(
            card,
            [
                ".goods-price__sale::text",
                ".product-card__price::text",
                ".S-product-item__price::text",
                "[class*='price']::text",
            ],
        ) or extract_price_from_text(card_text)
        image_url = normalize_url(
            first_attr(
                card,
                ["img"],
                ["src", "data-src", "data-original", "data-lazy-src", "data-she-src"],
            ),
            page.url,
        )

        if title and product_url:
            seen_urls.add(product_url)
            products.append(
                {
                    "title": title,
                    "price": price,
                    "product_url": product_url,
                    "image_url": image_url,
                    "crawl_time": crawl_time,
                    **extract_enhanced_fields_from_card(card, price),
                }
            )

    return products


def iter_json_objects(value: Any) -> list[dict[str, Any]]:
    """递归遍历 JSON 对象，查找可能的商品字典。"""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(iter_json_objects(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(iter_json_objects(child))
    return found


def extract_products_from_json(page: Any, crawl_time: str) -> list[dict[str, str]]:
    """从页面脚本 JSON 中兜底提取商品基础信息。"""
    products: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for script_text in page.css("script::text").getall():
        text = normalize_text(script_text)
        if not ("goods" in text.lower() or "product" in text.lower()):
            continue

        json_candidates = re.findall(r"<script[^>]*>(.*?)</script>", str(script_text), re.DOTALL)
        if not json_candidates:
            json_candidates = [str(script_text)]

        for candidate in json_candidates:
            candidate = candidate.strip()
            if not candidate.startswith(("{", "[")):
                continue
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue

            for item in iter_json_objects(data):
                title = normalize_text(
                    item.get("goods_name")
                    or item.get("goodsName")
                    or item.get("product_name")
                    or item.get("productName")
                    or item.get("name")
                    or item.get("title")
                )
                raw_url = normalize_text(
                    item.get("detail_url")
                    or item.get("detailUrl")
                    or item.get("goods_url")
                    or item.get("goodsUrl")
                    or item.get("url")
                )
                product_url = normalize_url(raw_url, page.url)
                if not title or not product_url or product_url in seen_urls:
                    continue

                price = normalize_text(
                    item.get("salePrice")
                    or item.get("sale_price")
                    or item.get("sale_price_text")
                    or item.get("salePriceText")
                    or item.get("retailPrice")
                    or item.get("retail_price")
                    or item.get("price")
                )
                original_price = normalize_text(
                    item.get("originalPrice")
                    or item.get("original_price")
                    or item.get("retailPrice")
                    or item.get("retail_price")
                    or item.get("marketPrice")
                    or item.get("market_price")
                )
                discount = normalize_text(
                    item.get("discount")
                    or item.get("discountPercent")
                    or item.get("discount_percent")
                    or item.get("discountLabel")
                    or item.get("discount_label")
                )
                rating = normalize_text(
                    item.get("rating")
                    or item.get("comment_rank_average")
                    or item.get("commentRankAverage")
                    or item.get("star")
                    or item.get("score")
                )
                review_count = normalize_text(
                    item.get("reviewCount")
                    or item.get("review_count")
                    or item.get("comment_num")
                    or item.get("commentNum")
                    or item.get("comments")
                )
                sales_tag = normalize_text(
                    item.get("salesTag")
                    or item.get("sales_tag")
                    or item.get("sellingPoint")
                    or item.get("selling_point")
                    or item.get("badge")
                    or item.get("tag")
                    or item.get("label")
                )
                image_url = normalize_url(
                    normalize_text(
                        item.get("goods_img")
                        or item.get("goodsImg")
                        or item.get("product_img")
                        or item.get("productImg")
                        or item.get("image")
                        or item.get("img")
                        or item.get("src")
                    ),
                    page.url,
                )
                seen_urls.add(product_url)
                products.append(
                    {
                        "title": title,
                        "price": price,
                        "product_url": product_url,
                        "image_url": image_url,
                        "crawl_time": crawl_time,
                        "original_price": original_price,
                        "discount": discount,
                        "rating": rating,
                        "review_count": review_count,
                        "sales_tag": sales_tag,
                    }
                )

    return products


def save_debug_html(page: Any) -> None:
    """保存当前页面 HTML，方便后续检查选择器。"""
    DEBUG_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    html = page.html_content
    DEBUG_HTML_PATH.write_text(str(html), encoding="utf-8")


def save_products_csv(products: list[dict[str, str]]) -> None:
    """保存商品数据到 CSV 文件。"""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=CSV_FIELDS,
        )
        writer.writeheader()
        writer.writerows(products)


def parse_page_arg() -> int:
    """读取命令行页码参数，未传入时默认采集第 1 页。"""
    parser = argparse.ArgumentParser(description="采集 SHEIN 新加坡站女装类目指定页。")
    parser.add_argument("page", nargs="?", type=int, default=1, help="要采集的页码，默认 1。")
    args = parser.parse_args()
    if args.page < 1:
        raise ValueError("页码必须大于等于 1。")
    return args.page


def build_target_url(page_number: int) -> str:
    """根据页码生成 SHEIN 女装类目分页 URL。"""
    if page_number == 1:
        return TARGET_URL
    return f"{TARGET_URL}?page={page_number}"


def configure_output_paths(page_number: int) -> None:
    """根据页码配置 CSV 和调试 HTML 输出路径。"""
    global DEBUG_HTML_PATH, CSV_PATH

    DEBUG_HTML_PATH = PROJECT_ROOT / "data" / "debug" / f"v2_3_page_{page_number}.html"
    CSV_PATH = PROJECT_ROOT / "data" / "output" / f"v2_3_products_page_{page_number}.csv"


def fetch_page_with_real_chrome(session: StealthySession, target_url: str) -> Any:
    """使用真实 Chrome 和持久化目录访问目标页面。"""
    return session.fetch(
        target_url,
        network_idle=True,
        wait=3000,
        timeout=90000,
        locale="en-SG",
        timezone_id="Asia/Singapore",
        page_action=scroll_first_page,
    )


def build_products_and_status(page: Any, crawl_time: str) -> tuple[list[dict[str, str]], str, str, dict[str, bool]]:
    """提取商品并计算页面状态。"""
    products = extract_products_from_dom(page, crawl_time)
    if not products:
        products = extract_products_from_json(page, crawl_time)

    page_status, result_suggestion, status_signals = judge_page_status(page, len(products))
    return products, page_status, result_suggestion, status_signals


def main() -> None:
    """执行单页采集验证流程。"""
    page_number = parse_page_arg()
    target_url = build_target_url(page_number)
    configure_output_paths(page_number)

    crawl_time = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # 使用 Scrapling 的 StealthySession 复用真实 Chrome 和持久化浏览器目录。
    with StealthySession(
        real_chrome=True,
        headless=False,
        user_data_dir=str(BROWSER_PROFILE_DIR),
    ) as session:
        page = fetch_page_with_real_chrome(session, target_url)
        products, page_status, result_suggestion, status_signals = build_products_and_status(page, crawl_time)

        # 如果检测到验证干扰，保持窗口打开，给人工完成验证留出时间，然后复用同一 Profile 再抓一次。
        if page_status in {"verification_suspected", "challenge_page"}:
            print("检测到验证干扰，浏览器窗口将保持打开 90 秒，请在窗口中完成人工验证。")
            sleep(90)
            page = fetch_page_with_real_chrome(session, target_url)
            products, page_status, result_suggestion, status_signals = build_products_and_status(page, crawl_time)

    save_products_csv(products)
    save_debug_html(page)

    page_title = first_text(page, ["title::text"])
    print(f"当前采集页码：{page_number}")
    print(f"当前 URL：{page.url}")
    print(f"页面标题：{page_title}")
    print(f"商品数量：{len(products)}")
    print(f"页面状态判断：{page_status}")
    print(f"本次结果建议：{result_suggestion}")
    print(f"CSV 保存路径：{CSV_PATH}")

    if not products:
        raise RuntimeError(f"未采集到商品数据，请检查 {DEBUG_HTML_PATH} 中的页面结构或拦截状态。")


if __name__ == "__main__":
    main()
