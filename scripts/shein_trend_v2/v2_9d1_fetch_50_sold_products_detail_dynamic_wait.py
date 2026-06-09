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
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_7_products_10_pages_merged.csv"
OUTPUT_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d1_50_sold_products_detail_attributes.csv"
SUMMARY_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d1_50_sold_products_detail_summary.csv"
DEBUG_DIR = PROJECT_ROOT / "data" / "debug" / "v2_9d1_50_sold_products"
MAX_PRODUCTS = 50
V29C_REFERENCE_SUCCESS_RATE = 0.95
FAST_MODE_MIN_CYCLE_SECONDS = 20
FAST_MODE_MIN_PAGE_SECONDS = 8
FAST_MODE_MAX_READY_LOOPS = 15
FAST_MODE_READY_INTERVAL_MS = 2000
FAST_MODE_MIN_ATTRIBUTE_COUNT = 5
TARGET_PRODUCTS_PER_MINUTE = 3
FREQUENCY_GUARD_ENABLED = True
DYNAMIC_WAIT_ENABLED = True
FIRST_PRODUCT_STABLE_ENABLED = True
MAX_ATTEMPTS_PER_PRODUCT = 2
STOP_ON_LOGIN_REQUIRED = True
STOP_ON_CAPTCHA = True
PROXY_URL = ""
BROWSER_WS_CDP_URL = os.getenv("BROWSER_WS_CDP_URL", "")
REMOTE_CDP_ENABLED = True
REMOTE_SESSION_RESTART_EVERY_SUCCESS = 2
REMOTE_SESSION_HARD_CAP_SECONDS = 60
REMOTE_SESSION_SAFE_SECONDS = 45
REMOTE_CDP_CONNECT_TIMEOUT_MS = 30000
REMOTE_RECONNECT_MAX_ATTEMPTS = 3
REMOTE_RECONNECT_COOLDOWN_SECONDS = 5


CONNECTION_CLOSED_KEYWORDS = [
    "ERR_CONNECTION_CLOSED",
    "unexpectedly closed the connection",
    "This site can't be reached",
    "site can't be reached",
]

CAPTCHA_VISIBLE_KEYWORDS = [
    "Please verify you are human",
    "verify you are human",
    "human verification",
    "security verification",
    "slide to verify",
    "verification code",
    "I'm not a robot",
    "Im not a robot",
    "recaptcha",
]

CAPTCHA_URL_KEYWORDS = [
    "captcha",
    "hcaptcha",
    "recaptcha",
    "cf-turnstile",
]

CAPTCHA_HTML_KEYWORDS = [
    "g-recaptcha",
    "hcaptcha",
    "h-captcha",
    "cf-turnstile",
    "turnstile",
    "data-sitekey",
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
    "fetch_mode",
    "fetch_seconds",
    "save_seconds",
    "parse_seconds",
    "product_total_seconds",
    "inter_sleep_seconds",
    "attempt_count",
    "recovery_used",
    "manual_wait_seconds",
    "stable_success_streak",
    "consecutive_failures",
    "fast_mode_min_cycle_seconds",
    "frequency_guard_enabled",
]


SUMMARY_FIELDS = [
    "total_planned",
    "total_output_rows",
    "page_success_count",
    "parse_success_count",
    "blocked_or_verify_count",
    "login_required_count",
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
    "total_elapsed_seconds",
    "average_seconds_per_product",
    "average_fetch_seconds",
    "average_save_seconds",
    "average_parse_seconds",
    "average_success_seconds_per_product",
    "max_product_seconds",
    "min_product_seconds",
    "average_cycle_seconds_per_product",
    "actual_products_per_minute",
    "target_products_per_minute",
    "fast_mode_min_cycle_seconds",
    "frequency_guard_enabled",
    "stable_mode_used_count",
    "fast_mode_used_count",
    "mode_switch_to_stable_count",
    "mode_switch_to_fast_count",
    "stopped_reason",
    "consecutive_failure_max",
    "dynamic_wait_enabled",
    "first_product_stable_enabled",
    "recovery_used_count",
    "manual_wait_count",
    "average_manual_wait_seconds",
    "max_attempts_per_product",
    "fast_to_stable_recovery_success_count",
    "fast_to_stable_recovery_failed_count",
    "remote_cdp_enabled",
    "remote_session_restart_every_success",
    "remote_session_hard_cap_seconds",
    "remote_session_safe_seconds",
    "remote_session_restart_count",
    "session_restart_count",
    "stop_on_login_required",
    "stop_on_captcha",
    "proxy_configured",
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
    """自动创建输出目录和调试目录。"""
    OUTPUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def create_remote_browser_session(playwright: Any) -> dict[str, Any]:
    """连接 browser.ws CDP，并建立本轮使用的远程页面。"""
    if not BROWSER_WS_CDP_URL:
        raise RuntimeError(
            "BROWSER_WS_CDP_URL 未配置。请先在终端设置 browser.ws 的 CDP WebSocket 地址。"
        )

    last_error: Exception | None = None
    for attempt in range(1, REMOTE_RECONNECT_MAX_ATTEMPTS + 1):
        try:
            print(
                "正在连接 browser.ws 远程 Session，"
                f"第 {attempt}/{REMOTE_RECONNECT_MAX_ATTEMPTS} 次尝试。"
            )
            browser = playwright.chromium.connect_over_cdp(
                BROWSER_WS_CDP_URL,
                timeout=REMOTE_CDP_CONNECT_TIMEOUT_MS,
            )
            contexts = browser.contexts
            context = contexts[0] if contexts else browser.new_context(
                locale="en-SG",
                timezone_id="Asia/Singapore",
            )
            page = context.new_page()
            print("browser.ws 远程 Session 连接成功。")
            return {
                "browser": browser,
                "context": context,
                "page": page,
                "started_at": time.monotonic(),
                "success_count": 0,
            }
        except Exception as exc:  # noqa: BLE001 - 远程服务短暂释放资源时允许重试。
            last_error = exc
            print(f"browser.ws 远程 Session 连接失败：{type(exc).__name__}: {exc}")
            if attempt < REMOTE_RECONNECT_MAX_ATTEMPTS:
                print(f"等待 {REMOTE_RECONNECT_COOLDOWN_SECONDS} 秒后重试连接。")
                time.sleep(REMOTE_RECONNECT_COOLDOWN_SECONDS)

    raise RuntimeError(
        f"browser.ws 远程 Session 连接连续失败 {REMOTE_RECONNECT_MAX_ATTEMPTS} 次：{last_error}"
    )


def close_remote_browser_session(remote_session: dict[str, Any] | None) -> None:
    """尽力关闭远程 page、context 和 browser，不让清理异常影响结果保存。"""
    if not remote_session:
        return
    try:
        page = remote_session.get("page")
        if page:
            page.close()
    except Exception:
        pass
    try:
        context = remote_session.get("context")
        if context:
            context.close()
    except Exception:
        pass
    try:
        browser = remote_session.get("browser")
        if browser:
            browser.close()
    except Exception:
        pass


def restart_remote_browser_session(
    playwright: Any,
    remote_session: dict[str, Any] | None,
) -> dict[str, Any]:
    """主动关闭并重新连接 browser.ws 远程 Session。"""
    print("正在主动关闭当前 browser.ws 远程浏览器 Session。")
    close_remote_browser_session(remote_session)
    print(f"等待 {REMOTE_RECONNECT_COOLDOWN_SECONDS} 秒，给 browser.ws 释放远程资源。")
    time.sleep(REMOTE_RECONNECT_COOLDOWN_SECONDS)
    print("正在重新连接 browser.ws 远程浏览器 Session。")
    return create_remote_browser_session(playwright)


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


def safe_page_text(browser_page: Any) -> str:
    try:
        return normalize_text(browser_page.locator("body").inner_text(timeout=1000))
    except Exception:  # noqa: BLE001 - Scrapling/Playwright page facades vary.
        return ""


def safe_page_html(browser_page: Any) -> str:
    try:
        return str(browser_page.content())
    except Exception:  # noqa: BLE001
        return ""


def safe_page_url(browser_page: Any) -> str:
    return str(getattr(browser_page, "url", "") or "")


def smart_wait_detail_ready(browser_page: Any) -> None:
    """Fast-mode dynamic wait: stop once product signals or Description attributes are ready."""
    start_time = time.monotonic()
    browser_page.wait_for_timeout(1000)
    for _ in range(FAST_MODE_MAX_READY_LOOPS):
        html_text = safe_page_html(browser_page)
        visible_text = safe_page_text(browser_page)
        if contains_visible_captcha_page(visible_text):
            return

        elapsed_seconds = time.monotonic() - start_time
        body_signal_count = count_product_body_signals(html_text, visible_text)
        attribute_count = len(extract_description_attributes(html_text))
        if elapsed_seconds >= FAST_MODE_MIN_PAGE_SECONDS:
            if attribute_count >= FAST_MODE_MIN_ATTRIBUTE_COUNT:
                return
            if body_signal_count >= 3 and attribute_count > 0:
                return
            if body_signal_count >= 4:
                return

        browser_page.mouse.wheel(0, 800)
        browser_page.wait_for_timeout(FAST_MODE_READY_INTERVAL_MS)


def fetch_detail_page(
    remote_session: dict[str, Any],
    product_url: str,
    fetch_mode: str,
) -> dict[str, str]:
    """通过 browser.ws 远程 Playwright page 访问商品详情页。"""
    page = remote_session["page"]
    start_time = time.monotonic()

    try:
        wait_until = "networkidle" if fetch_mode == "stable" else "domcontentloaded"
        timeout_ms = 90000 if fetch_mode == "stable" else 60000

        page.goto(product_url, wait_until=wait_until, timeout=timeout_ms)

        if fetch_mode == "stable":
            scroll_detail_page(page)
        else:
            smart_wait_detail_ready(page)

        html_text = page.content()
        visible_text = normalize_text(page.locator("body").inner_text(timeout=3000))
        final_url = page.url

        return {
            "html_text": html_text,
            "visible_text": visible_text,
            "final_url": final_url,
            "error_text": "",
            "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
        }
    except PlaywrightTimeoutError as exc:
        return {
            "html_text": safe_page_html(page),
            "visible_text": safe_page_text(page) or f"TimeoutError: {exc}",
            "final_url": safe_page_url(page) or product_url,
            "error_text": f"TimeoutError: {exc}",
            "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
        }
    except Exception as exc:
        return {
            "html_text": safe_page_html(page),
            "visible_text": safe_page_text(page) or f"{type(exc).__name__}: {exc}",
            "final_url": safe_page_url(page) or product_url,
            "error_text": f"{type(exc).__name__}: {exc}",
            "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
        }


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


def contains_visible_captcha_page(visible_text: str, error_text: str = "") -> bool:
    """只根据明确可见的人工验证文案判断验证码页面。"""
    text = f"{visible_text} {error_text}".lower()
    return any(keyword.lower() in text for keyword in CAPTCHA_VISIBLE_KEYWORDS)


def contains_captcha_page(final_url: str, html_text: str, visible_text: str, error_text: str) -> bool:
    if contains_visible_captcha_page(visible_text, error_text):
        return True

    final_url_lower = (final_url or "").lower()
    if any(keyword.lower() in final_url_lower for keyword in CAPTCHA_URL_KEYWORDS):
        return True

    visible_lower = (visible_text or "").lower()
    visible_context_keywords = [
        "human",
        "robot",
        "verify",
        "security verification",
        "captcha",
    ]
    has_visible_verification_context = any(keyword in visible_lower for keyword in visible_context_keywords)
    html_lower = (html_text or "").lower()
    has_captcha_component = any(keyword.lower() in html_lower for keyword in CAPTCHA_HTML_KEYWORDS)
    return has_captcha_component and has_visible_verification_context


def contains_login_page(final_url: str, html_text: str, visible_text: str) -> bool:
    final_url_lower = (final_url or "").lower()
    login_url_paths = [
        "/user/auth/login",
        "/user/auth/signin",
        "/auth/login",
    ]
    if any(path in final_url_lower for path in login_url_paths):
        return True

    def has_login_combo(text: str) -> bool:
        text_lower = (text or "").lower()
        combo_a = (
            "sign in/register" in text_lower
            and "mobile number or email address" in text_lower
            and "continue with google" in text_lower
        )
        combo_b = (
            "sign in/register" in text_lower
            and "continue with facebook" in text_lower
            and "can't access your account" in text_lower
        )
        combo_c = (
            "mobile number or email address" in text_lower
            and "continue with google" in text_lower
            and "continue with facebook" in text_lower
        )
        return combo_a or combo_b or combo_c

    return has_login_combo(visible_text) or has_login_combo(html_text)


def detect_page_status_legacy_disabled(
    html_text: str,
    visible_text: str,
    error_text: str,
    final_url: str,
    product_id: str,
    product_url: str,
) -> tuple[str, str]:
    """综合页面主体信息、异常信息和关键词判断页面状态。"""
    combined_text = f"{final_url} {html_text} {visible_text} {error_text}"

    if error_text:
        if contains_any(combined_text, CONNECTION_CLOSED_KEYWORDS):
            return "connection_closed", "页面或异常信息显示连接被关闭"
        if "timeout" in error_text.lower():
            return "timeout", "页面请求超时"
        return "fetch_failed", error_text[:300]

    if contains_login_page(final_url, html_text, visible_text):
        return "login_required", "明确登录页面"

    body_signal_count = count_product_body_signals(html_text, visible_text) if html_text else 0
    if body_signal_count >= 2:
        return "success", f"商品主体信息命中 {body_signal_count} 项"
    if contains_any(combined_text, CONNECTION_CLOSED_KEYWORDS):
        return "connection_closed", "页面或异常信息显示连接被关闭"
    if contains_any(combined_text, UNAVAILABLE_KEYWORDS):
        if "404" in combined_text or "page not found" in combined_text.lower():
            return "not_found", "页面显示 404 或 Page Not Found"
        return "product_unavailable", "页面显示商品不可用或已下架"
    if contains_captcha_page(final_url, html_text, visible_text, error_text):
        return "blocked_or_verify", "明确验证码页面"
    if final_url and final_url != product_url and product_id and product_id not in final_url:
        return "redirected", "最终 URL 与目标商品不一致"
    return "fetch_failed", "未获取到足够商品主体信息"


def detect_page_status(
    html_text: str,
    visible_text: str,
    error_text: str,
    final_url: str,
    product_id: str,
    product_url: str,
) -> tuple[str, str]:
    combined_text = f"{final_url} {html_text} {visible_text} {error_text}"

    if error_text:
        if contains_any(combined_text, CONNECTION_CLOSED_KEYWORDS):
            return "connection_closed", "页面或异常信息显示连接被关闭"
        if "timeout" in error_text.lower():
            return "timeout", "页面请求超时"
        return "fetch_failed", error_text[:300]

    if contains_login_page(final_url, html_text, visible_text):
        return "login_required", "明确登录页面"

    body_signal_count = count_product_body_signals(html_text, visible_text) if html_text else 0
    if body_signal_count >= 2:
        return "success", f"商品主体信息命中 {body_signal_count} 项"

    if contains_captcha_page(final_url, html_text, visible_text, error_text):
        return "blocked_or_verify", "明确验证码页面"

    if contains_any(combined_text, CONNECTION_CLOSED_KEYWORDS):
        return "connection_closed", "页面或异常信息显示连接被关闭"
    if contains_any(combined_text, UNAVAILABLE_KEYWORDS):
        if "404" in combined_text or "page not found" in combined_text.lower():
            return "not_found", "页面显示 404 或 Page Not Found"
        return "product_unavailable", "页面显示商品不可用或已下架"
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
            "fetch_mode": "",
            "fetch_seconds": "0.00",
            "save_seconds": "0.00",
            "parse_seconds": "0.00",
            "product_total_seconds": "0.00",
            "inter_sleep_seconds": "0.00",
            "attempt_count": "1",
            "recovery_used": "False",
            "manual_wait_seconds": "0.00",
            "stable_success_streak": "0",
            "consecutive_failures": "0",
            "fast_mode_min_cycle_seconds": str(FAST_MODE_MIN_CYCLE_SECONDS),
            "frequency_guard_enabled": str(FREQUENCY_GUARD_ENABLED),
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


def parse_float(value: Any) -> float:
    try:
        return float(normalize_text(value))
    except ValueError:
        return 0.0


def average_float(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_summary_row(
    total_planned: int,
    rows: list[dict[str, str]],
    total_elapsed_seconds: float = 0.0,
    stopped_reason: str = "",
    mode_switch_to_stable_count: int = 0,
    mode_switch_to_fast_count: int = 0,
    consecutive_failure_max: int = 0,
    session_restart_count: int = 0,
) -> dict[str, str]:
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
    fetch_seconds_values = [parse_float(row.get("fetch_seconds")) for row in rows]
    save_seconds_values = [parse_float(row.get("save_seconds")) for row in rows]
    parse_seconds_values = [parse_float(row.get("parse_seconds")) for row in rows]
    product_seconds_values = [parse_float(row.get("product_total_seconds")) for row in rows]
    manual_wait_seconds_values = [parse_float(row.get("manual_wait_seconds")) for row in rows]
    manual_wait_positive_values = [value for value in manual_wait_seconds_values if value > 0]
    recovery_rows = [row for row in rows if row.get("recovery_used") == "True"]
    recovery_success_rows = [
        row
        for row in recovery_rows
        if row.get("page_status") == "success" and row.get("parse_status") == "success"
    ]
    cycle_seconds_values = [
        parse_float(row.get("product_total_seconds")) + parse_float(row.get("inter_sleep_seconds")) for row in rows
    ]
    success_cycle_seconds_values = [
        parse_float(row.get("product_total_seconds")) + parse_float(row.get("inter_sleep_seconds"))
        for row in rows
        if row.get("page_status") == "success" and row.get("parse_status") == "success"
    ]
    average_cycle_seconds = average_float(cycle_seconds_values)
    actual_products_per_minute = 60 / average_cycle_seconds if average_cycle_seconds else 0.0
    return {
        "total_planned": str(total_planned),
        "total_output_rows": str(total_output_rows),
        "page_success_count": str(page_success_count),
        "parse_success_count": str(parse_success_count),
        "blocked_or_verify_count": str(sum(1 for row in rows if row.get("page_status") == "blocked_or_verify")),
        "login_required_count": str(sum(1 for row in rows if row.get("page_status") == "login_required")),
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
        "total_elapsed_seconds": f"{total_elapsed_seconds:.2f}",
        "average_seconds_per_product": f"{average_float(product_seconds_values):.2f}",
        "average_fetch_seconds": f"{average_float(fetch_seconds_values):.2f}",
        "average_save_seconds": f"{average_float(save_seconds_values):.2f}",
        "average_parse_seconds": f"{average_float(parse_seconds_values):.2f}",
        "average_success_seconds_per_product": f"{average_float(success_cycle_seconds_values):.2f}",
        "max_product_seconds": f"{max(product_seconds_values):.2f}" if product_seconds_values else "0.00",
        "min_product_seconds": f"{min(product_seconds_values):.2f}" if product_seconds_values else "0.00",
        "average_cycle_seconds_per_product": f"{average_cycle_seconds:.2f}",
        "actual_products_per_minute": f"{actual_products_per_minute:.2f}",
        "target_products_per_minute": str(TARGET_PRODUCTS_PER_MINUTE),
        "fast_mode_min_cycle_seconds": str(FAST_MODE_MIN_CYCLE_SECONDS),
        "frequency_guard_enabled": str(FREQUENCY_GUARD_ENABLED),
        "stable_mode_used_count": str(sum(1 for row in rows if row.get("fetch_mode") == "stable")),
        "fast_mode_used_count": str(sum(1 for row in rows if row.get("fetch_mode") == "fast")),
        "mode_switch_to_stable_count": str(mode_switch_to_stable_count),
        "mode_switch_to_fast_count": str(mode_switch_to_fast_count),
        "stopped_reason": stopped_reason,
        "consecutive_failure_max": str(consecutive_failure_max),
        "dynamic_wait_enabled": str(DYNAMIC_WAIT_ENABLED),
        "first_product_stable_enabled": str(FIRST_PRODUCT_STABLE_ENABLED),
        "recovery_used_count": str(len(recovery_rows)),
        "manual_wait_count": str(len(manual_wait_positive_values)),
        "average_manual_wait_seconds": f"{average_float(manual_wait_positive_values):.2f}",
        "max_attempts_per_product": str(MAX_ATTEMPTS_PER_PRODUCT),
        "fast_to_stable_recovery_success_count": str(
            sum(1 for row in recovery_success_rows if row.get("fetch_mode") == "fast_to_stable_recovery")
        ),
        "fast_to_stable_recovery_failed_count": str(
            sum(
                1
                for row in recovery_rows
                if row.get("fetch_mode") == "fast_to_stable_recovery"
                and not (row.get("page_status") == "success" and row.get("parse_status") == "success")
            )
        ),
        "remote_cdp_enabled": str(REMOTE_CDP_ENABLED),
        "remote_session_restart_every_success": str(REMOTE_SESSION_RESTART_EVERY_SUCCESS),
        "remote_session_hard_cap_seconds": str(REMOTE_SESSION_HARD_CAP_SECONDS),
        "remote_session_safe_seconds": str(REMOTE_SESSION_SAFE_SECONDS),
        "remote_session_restart_count": str(session_restart_count),
        "session_restart_count": str(session_restart_count),
        "stop_on_login_required": str(STOP_ON_LOGIN_REQUIRED),
        "stop_on_captcha": str(STOP_ON_CAPTCHA),
        "proxy_configured": str(bool(PROXY_URL)),
    }


def write_summary_csv(
    total_planned: int,
    rows: list[dict[str, str]],
    total_elapsed_seconds: float = 0.0,
    stopped_reason: str = "",
    mode_switch_to_stable_count: int = 0,
    mode_switch_to_fast_count: int = 0,
    consecutive_failure_max: int = 0,
    session_restart_count: int = 0,
) -> dict[str, str]:
    """写入 V2.9D 汇总 CSV，并返回汇总行。"""
    summary_row = build_summary_row(
        total_planned=total_planned,
        rows=rows,
        total_elapsed_seconds=total_elapsed_seconds,
        stopped_reason=stopped_reason,
        mode_switch_to_stable_count=mode_switch_to_stable_count,
        mode_switch_to_fast_count=mode_switch_to_fast_count,
        consecutive_failure_max=consecutive_failure_max,
        session_restart_count=session_restart_count,
    )
    SUMMARY_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerow(summary_row)
    return summary_row


def fetch_and_parse_one_product(
    remote_session: dict[str, Any],
    product: dict[str, str],
    current_mode: str,
) -> dict[str, str]:
    """在线采集 1 个真实销量商品详情页并解析 Description。"""
    product_url = normalize_text(product.get("product_url"))
    product_id = normalize_text(product.get("product_id")) or extract_product_id_from_url(product_url)
    paths = {
        "html": DEBUG_DIR / f"{product_id}.html",
        "visible_text": DEBUG_DIR / f"{product_id}_visible_text.txt",
        "description_raw_text": DEBUG_DIR / f"{product_id}_description_raw_text.txt",
    }
    row = build_base_row(product, paths)
    row["fetch_mode"] = current_mode

    html_text = ""
    visible_text = ""
    error_text = ""
    product_start_time = time.monotonic()
    fetch_seconds = 0.0
    save_seconds = 0.0
    parse_seconds = 0.0
    product_total_seconds = 0.0

    fetch_result = fetch_detail_page(remote_session, product_url, current_mode)
    html_text = fetch_result["html_text"]
    visible_text = fetch_result["visible_text"]
    error_text = fetch_result["error_text"]
    row["final_url"] = fetch_result["final_url"]
    fetch_seconds = parse_float(fetch_result["fetch_seconds"])

    if error_text and not html_text:
        html_text = "\n".join(
            [
                "<!doctype html>",
                "<html>",
                "<head><meta charset=\"utf-8\"><title>V2.9D-1 remote fetch failed</title></head>",
                "<body>",
                "<h1>V2.9D-1 远程商品详情页请求失败</h1>",
                f"<p>product_id：{html.escape(product_id)}</p>",
                f"<p>目标 URL：{html.escape(product_url)}</p>",
                f"<pre>{html.escape(error_text)}</pre>",
                "</body>",
                "</html>",
            ]
        )

    save_start_time = time.monotonic()
    save_text_file(paths["html"], html_text)
    save_text_file(paths["visible_text"], visible_text)
    save_seconds += time.monotonic() - save_start_time

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
    body_signal_count_debug = count_product_body_signals(html_text, visible_text) if html_text else 0
    attribute_count_debug = len(extract_description_attributes(html_text)) if html_text else 0
    print(
        f"debug_status: product_id={product_id}, "
        f"final_url={row['final_url']}, "
        f"body_signal_count={body_signal_count_debug}, "
        f"attribute_count_debug={attribute_count_debug}, "
        f"page_status={page_status}, "
        f"status_reason={status_reason}"
    )

    parse_start_time = time.monotonic()
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

    parse_seconds = time.monotonic() - parse_start_time
    save_start_time = time.monotonic()
    save_text_file(paths["description_raw_text"], row["raw_description_text"])
    save_seconds += time.monotonic() - save_start_time
    row["fetch_seconds"] = f"{fetch_seconds:.2f}"
    row["save_seconds"] = f"{save_seconds:.2f}"
    row["parse_seconds"] = f"{parse_seconds:.2f}"
    product_total_seconds = time.monotonic() - product_start_time
    row["product_total_seconds"] = f"{product_total_seconds:.2f}"
    return row


def calculate_inter_sleep_seconds(row: dict[str, str], next_mode: str) -> float:
    page_status = row.get("page_status")
    parse_status = row.get("parse_status")
    product_total_seconds = parse_float(row.get("product_total_seconds"))
    if page_status == "login_required":
        return 0.0
    if row.get("recovery_used") == "True":
        return random.uniform(20, 35)
    if page_status == "success" and parse_status == "success" and next_mode == "fast":
        if FREQUENCY_GUARD_ENABLED and product_total_seconds < FAST_MODE_MIN_CYCLE_SECONDS:
            return FAST_MODE_MIN_CYCLE_SECONDS - product_total_seconds + random.uniform(2, 5)
        return random.uniform(6, 10)
    if page_status == "success" and parse_status == "success" and next_mode == "stable":
        return random.uniform(10, 20)
    if page_status in {"timeout", "connection_closed", "fetch_failed"}:
        return random.uniform(15, 25)
    if page_status == "blocked_or_verify":
        return random.uniform(20, 35)
    return random.uniform(10, 20)


def is_success_row(row: dict[str, str]) -> bool:
    return row.get("page_status") == "success" and row.get("parse_status") == "success"


def is_captcha_status(row: dict[str, str]) -> bool:
    return row.get("page_status") == "blocked_or_verify" and row.get("status_reason") == "明确验证码页面"


def is_login_required_status(row: dict[str, str]) -> bool:
    return row.get("page_status") == "login_required" and row.get("status_reason") == "明确登录页面"


def count_key_fields(row: dict[str, str]) -> int:
    return sum(1 for field in KEY_FIELDS_FOR_STATS if row.get(field))


def should_stable_retry_due_to_empty_detail(row: dict[str, str]) -> bool:
    if row.get("page_status") in {"login_required", "blocked_or_verify"}:
        return False

    page_status = row.get("page_status")
    parse_status = row.get("parse_status")
    attribute_count = parse_int(row.get("attribute_count"))
    key_count = count_key_fields(row)

    return (
        page_status == "success"
        and parse_status in {"description_not_found", "parse_failed", "skipped_due_to_page_status"}
        and attribute_count == 0
        and key_count == 0
    )


def apply_attempt_metadata(
    row: dict[str, str],
    fetch_mode: str,
    attempt_count: int,
    recovery_used: bool,
    manual_wait_seconds: float,
    aggregate_rows: list[dict[str, str]],
) -> dict[str, str]:
    row["fetch_mode"] = fetch_mode
    row["attempt_count"] = str(attempt_count)
    row["recovery_used"] = str(recovery_used)
    row["manual_wait_seconds"] = f"{manual_wait_seconds:.2f}"
    row["fetch_seconds"] = f"{sum(parse_float(item.get('fetch_seconds')) for item in aggregate_rows):.2f}"
    row["save_seconds"] = f"{sum(parse_float(item.get('save_seconds')) for item in aggregate_rows):.2f}"
    row["parse_seconds"] = f"{sum(parse_float(item.get('parse_seconds')) for item in aggregate_rows):.2f}"
    row["product_total_seconds"] = (
        f"{sum(parse_float(item.get('product_total_seconds')) for item in aggregate_rows) + manual_wait_seconds:.2f}"
    )
    return row


def print_product_result(row: dict[str, str]) -> None:
    """输出单个商品采集结果。"""
    key_count = count_key_fields(row)
    print(
        "timing: "
        f"current_mode={row['fetch_mode']}, "
        f"product_id={row['product_id']}, "
        f"attempt_count={row['attempt_count']}, "
        f"recovery_used={row['recovery_used']}, "
        f"page_status={row['page_status']}, "
        f"parse_status={row['parse_status']}, "
        f"fetch_seconds={row['fetch_seconds']}, "
        f"save_seconds={row['save_seconds']}, "
        f"parse_seconds={row['parse_seconds']}, "
        f"product_total_seconds={row['product_total_seconds']}, "
        f"manual_wait_seconds={row['manual_wait_seconds']}, "
        f"inter_sleep_seconds={row['inter_sleep_seconds']}, "
        f"stable_success_streak={row['stable_success_streak']}, "
        f"consecutive_failures={row['consecutive_failures']}, "
        f"fast_mode_min_cycle_seconds={row['fast_mode_min_cycle_seconds']}, "
        f"frequency_guard_enabled={row['frequency_guard_enabled']}"
    )
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
    print(f"REMOTE_CDP_ENABLED: {REMOTE_CDP_ENABLED}")
    print(f"BROWSER_WS_CDP_URL configured: {bool(BROWSER_WS_CDP_URL)}")
    print(f"REMOTE_SESSION_RESTART_EVERY_SUCCESS: {REMOTE_SESSION_RESTART_EVERY_SUCCESS}")
    print(f"REMOTE_SESSION_HARD_CAP_SECONDS: {REMOTE_SESSION_HARD_CAP_SECONDS}")
    print(f"REMOTE_SESSION_SAFE_SECONDS: {REMOTE_SESSION_SAFE_SECONDS}")
    print(f"REMOTE_CDP_CONNECT_TIMEOUT_MS: {REMOTE_CDP_CONNECT_TIMEOUT_MS}")
    print(f"REMOTE_RECONNECT_MAX_ATTEMPTS: {REMOTE_RECONNECT_MAX_ATTEMPTS}")
    print(f"REMOTE_RECONNECT_COOLDOWN_SECONDS: {REMOTE_RECONNECT_COOLDOWN_SECONDS}")
    print(f"STOP_ON_LOGIN_REQUIRED: {STOP_ON_LOGIN_REQUIRED}")
    print(f"STOP_ON_CAPTCHA: {STOP_ON_CAPTCHA}")
    for index, product in enumerate(selected_products, start=1):
        print(
            f"待采集 {index}/{len(selected_products)}："
            f"product_id={product.get('product_id')}，"
            f"appear_count={product.get('appear_count')}，"
            f"sales_tag={product.get('sales_tag')}"
        )

    results: list[dict[str, str]] = []
    run_start_time = time.monotonic()
    current_mode = "stable"
    consecutive_failures = 0
    consecutive_failure_max = 0
    mode_switch_to_stable_count = 0
    mode_switch_to_fast_count = 0
    stopped_reason = ""
    session_restart_count = 0
    remote_session: dict[str, Any] | None = None
    with sync_playwright() as playwright:
        remote_session = create_remote_browser_session(playwright)
        try:
            for index, product in enumerate(selected_products, start=1):
                elapsed_remote_seconds = time.monotonic() - remote_session["started_at"]
                if elapsed_remote_seconds >= REMOTE_SESSION_SAFE_SECONDS:
                    print("当前 browser.ws 远程 Session 已接近 60 秒限制，主动重连。")
                    try:
                        remote_session = restart_remote_browser_session(playwright, remote_session)
                        remote_session["success_count"] = 0
                        session_restart_count += 1
                    except RuntimeError as exc:
                        stopped_reason = f"browser.ws 远程 Session 重连失败，本轮采集停止：{exc}"
                        print(stopped_reason)
                        remote_session = None
                        break

                product_id = normalize_text(product.get("product_id")) or extract_product_id_from_url(
                    normalize_text(product.get("product_url"))
                )
                print(f"\n开始采集 {index}/{len(selected_products)}：product_id={product_id}")
                first_attempt_mode = current_mode
                print(
                    f"\nProduct {index}/{len(selected_products)}: "
                    f"product_id={product_id}, first_attempt_mode={first_attempt_mode}"
                )
                first_row = fetch_and_parse_one_product(remote_session, product, first_attempt_mode)
                final_row = first_row
                attempt_count = 1
                recovery_used = False
                manual_wait_seconds = 0.0
                aggregate_rows = [first_row]
                final_fetch_mode = first_attempt_mode

                if (
                    first_attempt_mode == "fast"
                    and should_stable_retry_due_to_empty_detail(first_row)
                    and attempt_count < MAX_ATTEMPTS_PER_PRODUCT
                ):
                    recovery_used = True
                    mode_switch_to_stable_count += 1
                    print("fast_mode 未采集到有效详情属性，当前商品自动切换 stable_mode 重采一次。")
                    recovery_row = fetch_and_parse_one_product(remote_session, product, "stable")
                    aggregate_rows.append(recovery_row)
                    final_row = recovery_row
                    attempt_count = 2
                    final_fetch_mode = "fast_to_stable_empty_detail_retry"

                row = apply_attempt_metadata(
                    row=final_row,
                    fetch_mode=final_fetch_mode,
                    attempt_count=attempt_count,
                    recovery_used=recovery_used,
                    manual_wait_seconds=manual_wait_seconds,
                    aggregate_rows=aggregate_rows,
                )

                next_mode = "fast"
                is_success = is_success_row(row)
                if is_success:
                    consecutive_failures = 0
                    remote_session["success_count"] += 1
                else:
                    consecutive_failures += 1
                    consecutive_failure_max = max(consecutive_failure_max, consecutive_failures)

                inter_sleep_seconds = calculate_inter_sleep_seconds(row, next_mode)
                row["stable_success_streak"] = "0"
                row["consecutive_failures"] = str(consecutive_failures)
                row["inter_sleep_seconds"] = f"{inter_sleep_seconds:.2f}"
                results.append(row)
                write_output_csv(results)
                print_product_result(row)
                print(
                    f"attempt_count: {row['attempt_count']}\n"
                    f"first_attempt_mode: {first_attempt_mode}\n"
                    f"final_fetch_mode: {row['fetch_mode']}\n"
                    f"recovery_used: {row['recovery_used']}\n"
                    f"page_status: {row['page_status']}\n"
                    f"parse_status: {row['parse_status']}\n"
                    f"fetch_seconds: {row['fetch_seconds']}\n"
                    f"product_total_seconds: {row['product_total_seconds']}\n"
                    f"manual_wait_seconds: {row['manual_wait_seconds']}\n"
                    f"inter_sleep_seconds: {row['inter_sleep_seconds']}\n"
                    f"next_mode: {next_mode}"
                )

                if is_login_required_status(row):
                    print("检测到明确登录页面。")
                    print("当前商品结果已保存。")
                    print("正在安全重连 browser.ws 远程 Session，随后继续下一个商品。")
                    remote_session = restart_remote_browser_session(playwright, remote_session)
                    remote_session["success_count"] = 0
                    session_restart_count += 1
                    continue

                if is_captcha_status(row):
                    stopped_reason = "检测到明确验证码页面，本轮采集停止"
                    print("检测到明确验证码页面。")
                    print("当前商品已保存，请检查 debug HTML 和 visible_text。")
                    print("为避免继续批量产生空字段，本轮采集停止。")
                    close_remote_browser_session(remote_session)
                    remote_session = None
                    break

                if consecutive_failures >= 5:
                    stopped_reason = "Consecutive failures reached 5; collection stopped automatically"
                    print(stopped_reason)
                    break

                if index < len(selected_products):
                    sleep_seconds = inter_sleep_seconds
                    print(f"等待 {sleep_seconds} 秒后继续下一个商品...")
                    time.sleep(sleep_seconds)
                if current_mode != next_mode:
                    mode_switch_to_fast_count += 1
                current_mode = next_mode

                if (
                    is_success
                    and row["page_status"] == "success"
                    and row["parse_status"] == "success"
                    and remote_session["success_count"] >= REMOTE_SESSION_RESTART_EVERY_SUCCESS
                    and index < len(selected_products)
                ):
                    print(
                        "browser.ws 远程 Session 已成功采集 "
                        f"{REMOTE_SESSION_RESTART_EVERY_SUCCESS} 个商品，主动重连以适配 60 秒 hard cap。"
                    )
                    try:
                        remote_session = restart_remote_browser_session(playwright, remote_session)
                        remote_session["success_count"] = 0
                        session_restart_count += 1
                    except RuntimeError as exc:
                        stopped_reason = f"browser.ws 远程 Session 重连失败，本轮采集停止：{exc}"
                        print(stopped_reason)
                        remote_session = None
                        break
        finally:
            close_remote_browser_session(remote_session)

    write_output_csv(results)
    success_count = sum(1 for row in results if row["page_status"] == "success")
    parse_success_count = sum(1 for row in results if row["parse_status"] == "success")
    total_elapsed_seconds = time.monotonic() - run_start_time
    summary_row = write_summary_csv(
        len(selected_products),
        results,
        total_elapsed_seconds=total_elapsed_seconds,
        stopped_reason=stopped_reason,
        mode_switch_to_stable_count=mode_switch_to_stable_count,
        mode_switch_to_fast_count=mode_switch_to_fast_count,
        consecutive_failure_max=consecutive_failure_max,
        session_restart_count=session_restart_count,
    )

    print("\nV2.9D 50 个样本详情采集完成")
    print("=" * 64)
    print(f"候选真实 sold 商品数量：{len(sold_candidates)}")
    print(f"本次计划采集商品数：{len(selected_products)}")
    print(f"page_status = success 数量：{success_count}")
    print(f"parse_status = success 数量：{parse_success_count}")
    print(f"blocked_or_verify count: {summary_row['blocked_or_verify_count']}")
    print(f"login_required count: {summary_row['login_required_count']}")
    print(f"connection_closed count: {summary_row['connection_closed_count']}")
    print(f"timeout count: {summary_row['timeout_count']}")
    print(f"fetch_failed count: {summary_row['fetch_failed_count']}")
    print(f"product_unavailable count: {summary_row['product_unavailable_count']}")
    print(f"not_found count: {summary_row['not_found_count']}")
    print(f"remote_cdp_enabled: {summary_row['remote_cdp_enabled']}")
    print(
        "remote_session_restart_every_success: "
        f"{summary_row['remote_session_restart_every_success']}"
    )
    print(f"remote_session_hard_cap_seconds: {summary_row['remote_session_hard_cap_seconds']}")
    print(f"remote_session_safe_seconds: {summary_row['remote_session_safe_seconds']}")
    print(f"remote_session_restart_count: {summary_row['remote_session_restart_count']}")
    print(f"stop_on_login_required: {summary_row['stop_on_login_required']}")
    print(f"stop_on_captcha: {summary_row['stop_on_captcha']}")
    print(f"proxy_configured: {summary_row['proxy_configured']}")
    if selected_products:
        success_rate_value = success_count / len(selected_products)
        if success_rate_value < V29C_REFERENCE_SUCCESS_RATE - 0.05:
            print("提示：本次 success_rate 明显低于 V2.9C 参考值，可能存在网络波动或访问节奏压力问题。")
    for row in results:
        key_count = count_key_fields(row)
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
