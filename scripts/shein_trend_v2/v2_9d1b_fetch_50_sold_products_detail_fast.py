"""V2.9D-1B：local Playwright + KDL proxy detail collection.

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

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - runtime dependency hint.
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRETS_ENV_PATH = PROJECT_ROOT / "secrets" / "kdl_proxy.env"

if SECRETS_ENV_PATH.exists():
    if load_dotenv is None:
        raise RuntimeError("请先执行：pip install python-dotenv")
    load_dotenv(SECRETS_ENV_PATH, override=False)

INPUT_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_7_products_10_pages_merged.csv"
OUTPUT_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d1b_50_sold_products_detail_attributes_fast.csv"
SUMMARY_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d1b_50_sold_products_detail_summary_fast.csv"
PREFLIGHT_MATRIX_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d1b_preflight_matrix.csv"
DEBUG_DIR = PROJECT_ROOT / "data" / "debug" / "v2_9d1b_50_sold_products_fast"
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
STOP_ON_CAPTCHA = False
CAPTCHA_MANUAL_RESOLVE_TIMEOUT_SECONDS = 180
CAPTCHA_MANUAL_POLL_INTERVAL_SECONDS = 2
PROXY_SERVER = os.getenv("KDL_PROXY_SERVER", "")
PROXY_USERNAME = os.getenv("KDL_PROXY_USERNAME", "")
PROXY_PASSWORD = os.getenv("KDL_PROXY_PASSWORD", "")
PROXY_CONFIGURED = bool(PROXY_SERVER and PROXY_USERNAME and PROXY_PASSWORD)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
FINGERPRINT_MASK_ENABLED = True
FAST_DETAIL_TIMEOUT_MS = 18000
STABLE_DETAIL_TIMEOUT_MS = 90000
FAST_PRODUCT_HARD_CAP_SECONDS = 30
STABLE_PRODUCT_HARD_CAP_SECONDS = 100
RESOURCE_BLOCKING_ENABLED = False
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
PREFLIGHT_CHECK_ENABLED = True
PREFLIGHT_HOME_URL = "https://sg.shein.com/"
PREFLIGHT_CATEGORY_URL = "https://sg.shein.com/Women-Clothing-c-2030.html"
PREFLIGHT_TIMEOUT_MS = 8000
PROXY_PREFLIGHT_TIMEOUT_MS = 30000
PREFLIGHT_OBSERVE_SECONDS = 5
PREFLIGHT_POLL_INTERVAL_MS = 500
PREFLIGHT_MATRIX_ENABLED = False
DETAIL_DIRECT_MODE_ENABLED = True
CATEGORY_PREFLIGHT_REQUIRED = False
MAX_CONSECUTIVE_BLOCKED_PRODUCTS = 3
PREFLIGHT_MATRIX_TARGETS = [
    ("home", "https://sg.shein.com/"),
    ("women_category", "https://sg.shein.com/Women-Clothing-c-2030.html"),
    ("search_tshirt", "https://sg.shein.com/pdsearch/T%20shirt/"),
    ("search_pants", "https://sg.shein.com/pdsearch/pants/"),
]
LOCAL_FAST_EMPTY_DETAIL_STABLE_COOLDOWN = 3


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
    "/risk/challenge",
    "captcha_type=",
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
    "captcha_wait_used",
    "captcha_wait_seconds",
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
    "captcha_wait_used_count",
    "captcha_recovery_success_count",
    "captcha_recovery_failed_count",
    "average_captcha_wait_seconds",
    "max_attempts_per_product",
    "fast_to_stable_recovery_success_count",
    "fast_to_stable_recovery_failed_count",
    "detail_direct_mode_enabled",
    "category_preflight_required",
    "max_consecutive_blocked_products",
    "preflight_check_enabled",
    "proxy_preflight_status",
    "proxy_preflight_reason",
    "session_type",
    "proxy_configured",
    "fingerprint_mask_enabled",
    "user_agent_configured",
    "stop_on_login_required",
    "stop_on_captcha",
]

PREFLIGHT_MATRIX_FIELDS = [
    "label",
    "target_url",
    "final_url",
    "status",
    "reason",
    "body_signal_count",
    "elapsed_seconds",
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


def install_resource_blocking(page: Any) -> None:
    """只阻断图片、媒体和字体，不影响脚本、样式及 Description API。"""
    blocked_resource_types = BLOCKED_RESOURCE_TYPES

    def route_handler(route: Any, request: Any) -> None:
        try:
            if request.resource_type in blocked_resource_types:
                route.abort()
                return
            route.continue_()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    page.route("**/*", route_handler)


def create_local_proxy_browser_session(playwright: Any) -> dict[str, Any]:
    """Launch local Chromium with the configured KDL proxy."""
    if not PROXY_CONFIGURED:
        raise RuntimeError(
            "KDL proxy is not configured. Set KDL_PROXY_SERVER, "
            "KDL_PROXY_USERNAME, and KDL_PROXY_PASSWORD."
        )

    browser = playwright.chromium.launch(
        headless=False,
        proxy={
            "server": PROXY_SERVER,
            "username": PROXY_USERNAME,
            "password": PROXY_PASSWORD,
        },
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
        ],
    )
    context = browser.new_context(
        locale="en-SG",
        timezone_id="Asia/Singapore",
        user_agent=USER_AGENT,
        viewport={"width": 1366, "height": 768},
        screen={"width": 1366, "height": 768},
        device_scale_factor=1,
        is_mobile=False,
        has_touch=False,
    )
    context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        window.chrome = window.chrome || {};
        window.chrome.runtime = window.chrome.runtime || {};
        const originalQuery = window.navigator.permissions.query.bind(
            window.navigator.permissions
        );
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-SG', 'en-US', 'en']
        });
        """
    )
    page = context.new_page()
    if RESOURCE_BLOCKING_ENABLED:
        install_resource_blocking(page)
    return {
        "browser": browser,
        "context": context,
        "page": page,
        "started_at": time.monotonic(),
        "success_count": 0,
        "session_type": "local_proxy",
    }


def close_browser_session(session: dict[str, Any] | None) -> None:
    """Best-effort cleanup for page, context, and browser."""
    if not session:
        return
    try:
        page = session.get("page")
        if page:
            page.close()
    except Exception:
        pass
    try:
        context = session.get("context")
        if context:
            context.close()
    except Exception:
        pass
    try:
        browser = session.get("browser")
        if browser:
            browser.close()
    except Exception:
        pass


def safe_proxy_failure_reason(exc: Exception) -> str:
    """Return a proxy failure summary without host, username, or password details."""
    message = normalize_text(exc)
    for secret_value in (PROXY_PASSWORD, PROXY_USERNAME, PROXY_SERVER):
        if secret_value:
            message = message.replace(secret_value, "[redacted]")
    if not message:
        message = "no exception message"
    return f"{type(exc).__name__}: {message[:300]}"


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


def is_early_escape_url(url: str) -> bool:
    """识别明确风险挑战或登录 URL，仅用于尽快结束等待。"""
    lower_url = (url or "").lower()
    return any(
        marker in lower_url
        for marker in [
            "/risk/challenge",
            "captcha_type=",
        ]
    )


def product_hard_cap_seconds(fetch_mode: str) -> float:
    """返回当前采集模式的单商品硬截止秒数。"""
    return STABLE_PRODUCT_HARD_CAP_SECONDS if fetch_mode == "stable" else FAST_PRODUCT_HARD_CAP_SECONDS


def is_product_hard_cap_exceeded(start_time: float, fetch_mode: str) -> bool:
    """判断单商品采集是否达到当前模式的硬截止。"""
    return time.monotonic() - start_time >= product_hard_cap_seconds(fetch_mode)


def wait_with_product_hard_cap(
    browser_page: Any,
    product_start_time: float,
    fetch_mode: str,
    requested_ms: int,
) -> bool:
    """在剩余硬截止时间内等待，返回等待后是否仍可继续。"""
    remaining_seconds = product_hard_cap_seconds(fetch_mode) - (time.monotonic() - product_start_time)
    if remaining_seconds <= 0:
        return False
    browser_page.wait_for_timeout(min(requested_ms, max(1, int(remaining_seconds * 1000))))
    return not is_product_hard_cap_exceeded(product_start_time, fetch_mode)


def scroll_detail_page(browser_page: Any, product_start_time: float, fetch_mode: str) -> None:
    """在 stable 商品硬截止内轻量滚动，触发详情属性加载。"""
    if not wait_with_product_hard_cap(browser_page, product_start_time, fetch_mode, 3000):
        return
    for _ in range(3):
        final_url = safe_page_url(browser_page)
        if is_early_escape_url(final_url):
            print(f"检测到提前逃生 URL，停止 stable 等待：{final_url}")
            return
        if is_product_hard_cap_exceeded(product_start_time, fetch_mode):
            print(f"{fetch_mode} 商品达到单商品硬截止，停止等待。")
            return
        browser_page.mouse.wheel(0, 1000)
        if not wait_with_product_hard_cap(browser_page, product_start_time, fetch_mode, 1000):
            return


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


def smart_wait_detail_ready(browser_page: Any, product_start_time: float, fetch_mode: str) -> None:
    """Fast-mode dynamic wait: stop once product signals or Description attributes are ready."""
    start_time = time.monotonic()
    browser_page.wait_for_timeout(1000)
    min_page_seconds = FAST_MODE_MIN_PAGE_SECONDS
    min_attribute_count = FAST_MODE_MIN_ATTRIBUTE_COUNT

    for _ in range(FAST_MODE_MAX_READY_LOOPS):
        final_url = safe_page_url(browser_page)
        if is_early_escape_url(final_url):
            print(f"检测到提前逃生 URL，停止 fast 等待：{final_url}")
            return
        if is_product_hard_cap_exceeded(product_start_time, fetch_mode):
            print(f"{fetch_mode} 商品达到单商品硬截止，停止等待。")
            return

        html_text = safe_page_html(browser_page)
        visible_text = safe_page_text(browser_page)
        if contains_visible_captcha_page(visible_text):
            return

        elapsed_seconds = time.monotonic() - start_time
        body_signal_count = count_product_body_signals(html_text, visible_text)
        attribute_count = len(extract_description_attributes(html_text))
        if elapsed_seconds >= min_page_seconds:
            if attribute_count >= min_attribute_count:
                return
            if body_signal_count >= 3 and attribute_count > 0:
                return
            if body_signal_count >= 4:
                return

        browser_page.mouse.wheel(0, 800)
        if not wait_with_product_hard_cap(
            browser_page,
            product_start_time,
            fetch_mode,
            FAST_MODE_READY_INTERVAL_MS,
        ):
            return


def fetch_detail_page(
    session: dict[str, Any],
    product_url: str,
    fetch_mode: str,
) -> dict[str, str]:
    """Use the current local Playwright page to visit the product detail page."""
    page = session["page"]
    start_time = time.monotonic()

    try:
        wait_until = "networkidle" if fetch_mode == "stable" else "domcontentloaded"
        timeout_ms = STABLE_DETAIL_TIMEOUT_MS if fetch_mode == "stable" else FAST_DETAIL_TIMEOUT_MS

        page.goto(product_url, wait_until=wait_until, timeout=timeout_ms)

        current_url = safe_page_url(page)
        if is_early_escape_url(current_url):
            print(f"检测到提前逃生 URL，停止详情页等待：{current_url}")
            return {
                "html_text": safe_page_html(page),
                "visible_text": safe_page_text(page),
                "final_url": current_url,
                "error_text": "",
                "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
            }

        if is_product_hard_cap_exceeded(start_time, fetch_mode):
            return {
                "html_text": safe_page_html(page),
                "visible_text": safe_page_text(page),
                "final_url": safe_page_url(page) or product_url,
                "error_text": f"ProductHardCapExceeded: {fetch_mode} 商品采集超过硬截止",
                "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
            }

        if fetch_mode == "stable":
            scroll_detail_page(page, start_time, fetch_mode)
        else:
            smart_wait_detail_ready(page, start_time, fetch_mode)

        if is_product_hard_cap_exceeded(start_time, fetch_mode):
            return {
                "html_text": safe_page_html(page),
                "visible_text": safe_page_text(page),
                "final_url": safe_page_url(page) or product_url,
                "error_text": f"ProductHardCapExceeded: {fetch_mode} 商品采集超过硬截止",
                "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
            }

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
    """Identify explicit SHEIN login redirects from the final URL."""
    final_url_lower = (final_url or "").lower()
    if "/user/auth/login" in final_url_lower or "/auth/login" in final_url_lower:
        return True

    combined_text = f"{visible_text} {html_text}".lower()
    login_markers = [
        "sign in/register",
        "mobile number or email address",
        "continue with google",
        "continue with facebook",
        "can't access your account",
        "your data is protected",
    ]
    marker_count = sum(1 for marker in login_markers if marker in combined_text)
    return marker_count >= 2


def run_preflight_check(session: dict[str, Any]) -> tuple[bool, str]:
    """检查首页，并按配置决定类目页失败是否阻断详情直连采集。"""
    page = session["page"]
    targets = [
        ("home", PREFLIGHT_HOME_URL),
        ("category", PREFLIGHT_CATEGORY_URL),
    ]

    def handle_failure(label: str, reason: str) -> tuple[bool, str]:
        if label == "category" and not CATEGORY_PREFLIGHT_REQUIRED:
            print(f"类目页预检失败原因：{reason}")
            print("类目页预检未通过，但 CATEGORY_PREFLIGHT_REQUIRED=False。")
            print("本轮继续采用商品详情直连模式。")
            return True, "首页预检通过；类目页预检失败但已忽略，进入商品详情直连模式"
        return False, reason

    for label, url in targets:
        print(f"开始本地代理入口预检：{label} -> {url}")
        start_time = time.monotonic()
        try:
            try:
                page.goto(url, wait_until="commit", timeout=PREFLIGHT_TIMEOUT_MS)
            except Exception as commit_exc:  # noqa: BLE001 - 兼容不支持 commit 的旧版 Playwright。
                error_text = str(commit_exc).lower()
                commit_not_supported = (
                    "wait_until" in error_text
                    and "commit" in error_text
                    and any(marker in error_text for marker in ("invalid", "expected", "unsupported"))
                )
                if not commit_not_supported:
                    raise
                page.goto(url, wait_until="domcontentloaded", timeout=PREFLIGHT_TIMEOUT_MS)

            final_url = safe_page_url(page)
            if is_early_escape_url(final_url):
                return handle_failure(
                    label,
                    f"入口预检失败：{label} 页面进入风险/登录页面：{final_url}",
                )

            observe_start = time.monotonic()
            while time.monotonic() - observe_start < PREFLIGHT_OBSERVE_SECONDS:
                final_url = safe_page_url(page)
                if is_early_escape_url(final_url):
                    return handle_failure(
                        label,
                        f"入口预检失败：{label} 页面进入风险/登录页面：{final_url}",
                    )

                visible_text = safe_page_text(page)
                if contains_visible_captcha_page(visible_text):
                    return handle_failure(
                        label,
                        f"入口预检失败：{label} 页面出现明确验证码文案",
                    )

                page.wait_for_timeout(PREFLIGHT_POLL_INTERVAL_MS)

            final_url = safe_page_url(page)
            visible_text = safe_page_text(page)
            html_text = safe_page_html(page)
            body_signal_count = count_product_body_signals(html_text, visible_text) if html_text else 0

            print(
                f"entry_check_status: label={label}, "
                f"final_url={final_url}, "
                f"body_signal_count={body_signal_count}, "
                f"elapsed_seconds={time.monotonic() - start_time:.2f}"
            )

            if is_early_escape_url(final_url):
                return handle_failure(
                    label,
                    f"入口预检失败：{label} 页面进入风险/登录页面：{final_url}",
                )
            if contains_visible_captcha_page(visible_text):
                return handle_failure(
                    label,
                    f"入口预检失败：{label} 页面出现明确验证码文案",
                )
            if contains_login_page(final_url, html_text, visible_text):
                return handle_failure(
                    label,
                    f"入口预检失败：{label} 页面出现明确登录页面",
                )
        except Exception as exc:  # noqa: BLE001 - 预检失败应安全停止而非抛 traceback。
            return handle_failure(
                label,
                f"入口预检失败：{label} 页面请求异常：{type(exc).__name__}: {exc}",
            )

    return True, "入口预检通过：首页和女装类目页均可访问"


def run_proxy_preflight(session: dict[str, Any]) -> tuple[str, str]:
    """Confirm the local Chromium session reaches api.ipify.org through the proxy."""
    page = session["page"]
    try:
        page.goto("https://api.ipify.org", wait_until="domcontentloaded", timeout=PROXY_PREFLIGHT_TIMEOUT_MS)
        body_text = normalize_text(safe_page_text(page))
        if body_text and re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", body_text):
            return "success", "api_ipify_success"
        if body_text:
            return "failed", "api_ipify_non_ip_response"
        return "failed", "api_ipify_empty_response"
    except PlaywrightTimeoutError:
        return "failed", "TimeoutError: api_ipify_timeout"
    except Exception as exc:  # noqa: BLE001 - only a safe summary is written.
        return "failed", safe_proxy_failure_reason(exc)


def run_preflight_matrix(
    session: dict[str, Any],
    selected_products: list[dict[str, str]],
) -> list[dict[str, str]]:
    """依次诊断固定入口和前三个商品入口，不采集或解析详情属性。"""
    context = session["context"]
    targets = list(PREFLIGHT_MATRIX_TARGETS)
    for index, product in enumerate(selected_products[:3], start=1):
        product_url = normalize_text(product.get("product_url"))
        if product_url:
            targets.append((f"top_product_{index}", product_url))

    rows: list[dict[str, str]] = []
    for label, target_url in targets:
        print(f"开始 Preflight Matrix 入口诊断：{label} -> {target_url}")
        start_time = time.monotonic()
        page = None
        final_url = ""
        visible_text = ""
        html_text = ""
        status = "unknown"
        reason = "未命中风险页，也未命中足够页面主体信号"
        body_signal_count = 0

        try:
            page = context.new_page()
            if RESOURCE_BLOCKING_ENABLED:
                install_resource_blocking(page)
            page.goto(target_url, wait_until="commit", timeout=PREFLIGHT_TIMEOUT_MS)
            final_url = safe_page_url(page)

            if is_early_escape_url(final_url):
                status = "blocked_or_verify"
                reason = "进入风险或登录页面"
            else:
                observe_start = time.monotonic()
                while time.monotonic() - observe_start < PREFLIGHT_OBSERVE_SECONDS:
                    final_url = safe_page_url(page)
                    if is_early_escape_url(final_url):
                        status = "blocked_or_verify"
                        reason = "进入风险或登录页面"
                        break

                    visible_text = safe_page_text(page)
                    if contains_visible_captcha_page(visible_text):
                        status = "visible_captcha"
                        reason = "出现明确验证码文案"
                        break

                    page.wait_for_timeout(PREFLIGHT_POLL_INTERVAL_MS)

                if status == "unknown":
                    final_url = safe_page_url(page)
                    visible_text = safe_page_text(page)
                    html_text = safe_page_html(page)
                    body_signal_count = count_product_body_signals(html_text, visible_text)

                    if is_early_escape_url(final_url):
                        status = "blocked_or_verify"
                        reason = "进入风险或登录页面"
                    elif contains_visible_captcha_page(visible_text):
                        status = "visible_captcha"
                        reason = "出现明确验证码文案"
                    elif body_signal_count >= 2:
                        status = "accessible"
                        reason = "页面主体信号正常"
        except Exception as exc:  # noqa: BLE001 - 单个入口异常只记录结果，不中断矩阵诊断。
            final_url = safe_page_url(page) if page else ""
            visible_text = safe_page_text(page) if page else ""
            if is_early_escape_url(final_url):
                status = "blocked_or_verify"
                reason = "进入风险或登录页面"
            elif contains_visible_captcha_page(visible_text):
                status = "visible_captcha"
                reason = "出现明确验证码文案"
            else:
                status = "unknown"
                reason = f"入口请求异常：{type(exc).__name__}: {exc}"
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

        elapsed_seconds = time.monotonic() - start_time
        row = {
            "label": label,
            "target_url": target_url,
            "final_url": final_url,
            "status": status,
            "reason": reason,
            "body_signal_count": str(body_signal_count),
            "elapsed_seconds": f"{elapsed_seconds:.2f}",
        }
        rows.append(row)
        print(
            f"matrix_status: label={label}, "
            f"final_url={final_url}, "
            f"status={status}, "
            f"body_signal_count={body_signal_count}, "
            f"elapsed_seconds={elapsed_seconds:.2f}"
        )

    return rows


def write_preflight_matrix_csv(rows: list[dict[str, str]]) -> None:
    """写入 Preflight Matrix 入口诊断结果。"""
    PREFLIGHT_MATRIX_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PREFLIGHT_MATRIX_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=PREFLIGHT_MATRIX_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


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
    final_url_lower = (final_url or "").lower()

    if contains_login_page(final_url, html_text, visible_text):
        return "login_required", "明确登录页面"

    if "/risk/challenge" in final_url_lower or "captcha_type=" in final_url_lower:
        return "blocked_or_verify", "明确验证码页面"

    if "ProductHardCapExceeded" in error_text:
        attribute_count_debug = len(extract_description_attributes(html_text)) if html_text else 0
        if attribute_count_debug >= FAST_MODE_MIN_ATTRIBUTE_COUNT:
            return "success", "商品属性已加载，虽达到 fast 硬截止但保留成功结果"

    if error_text:
        if contains_any(combined_text, CONNECTION_CLOSED_KEYWORDS):
            return "connection_closed", "页面或异常信息显示连接被关闭"
        if "timeout" in error_text.lower():
            return "timeout", "页面请求超时"
        return "fetch_failed", error_text[:300]

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
            "captcha_wait_used": "False",
            "captcha_wait_seconds": "0.00",
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
    proxy_preflight_status: str = "",
    proxy_preflight_reason: str = "",
    session_type: str = "local_proxy",
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
    captcha_wait_rows = [row for row in rows if row.get("captcha_wait_used") == "True"]
    captcha_wait_seconds_values = [parse_float(row.get("captcha_wait_seconds")) for row in captcha_wait_rows]
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
        "captcha_wait_used_count": str(len(captcha_wait_rows)),
        "captcha_recovery_success_count": str(
            sum(
                1
                for row in captcha_wait_rows
                if row.get("page_status") == "success" and row.get("parse_status") == "success"
            )
        ),
        "captcha_recovery_failed_count": str(
            sum(
                1
                for row in captcha_wait_rows
                if not (row.get("page_status") == "success" and row.get("parse_status") == "success")
            )
        ),
        "average_captcha_wait_seconds": f"{average_float(captcha_wait_seconds_values):.2f}",
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
        "detail_direct_mode_enabled": str(DETAIL_DIRECT_MODE_ENABLED),
        "category_preflight_required": str(CATEGORY_PREFLIGHT_REQUIRED),
        "max_consecutive_blocked_products": str(MAX_CONSECUTIVE_BLOCKED_PRODUCTS),
        "preflight_check_enabled": str(PREFLIGHT_CHECK_ENABLED),
        "proxy_preflight_status": proxy_preflight_status,
        "proxy_preflight_reason": proxy_preflight_reason,
        "session_type": session_type,
        "proxy_configured": str(PROXY_CONFIGURED),
        "fingerprint_mask_enabled": str(FINGERPRINT_MASK_ENABLED),
        "user_agent_configured": str(bool(USER_AGENT)),
        "stop_on_login_required": str(STOP_ON_LOGIN_REQUIRED),
        "stop_on_captcha": str(STOP_ON_CAPTCHA),
    }


def write_summary_csv(
    total_planned: int,
    rows: list[dict[str, str]],
    total_elapsed_seconds: float = 0.0,
    stopped_reason: str = "",
    mode_switch_to_stable_count: int = 0,
    mode_switch_to_fast_count: int = 0,
    consecutive_failure_max: int = 0,
    proxy_preflight_status: str = "",
    proxy_preflight_reason: str = "",
    session_type: str = "local_proxy",
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
        proxy_preflight_status=proxy_preflight_status,
        proxy_preflight_reason=proxy_preflight_reason,
        session_type=session_type,
    )
    SUMMARY_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerow(summary_row)
    return summary_row


def fetch_and_parse_one_product(
    session: dict[str, Any],
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

    fetch_result = fetch_detail_page(session, product_url, current_mode)
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
    if row.get("captcha_wait_used") == "True":
        return random.uniform(20, 35)
    if page_status in {"blocked_or_verify", "login_required"}:
        return 0.0
    if page_status in {"timeout", "connection_closed", "fetch_failed"}:
        return random.uniform(3, 6)
    if parse_status == "skipped_due_to_page_status":
        return random.uniform(3, 6)
    if row.get("recovery_used") == "True":
        return random.uniform(20, 35)
    if page_status == "success" and parse_status == "success" and next_mode == "fast":
        if FREQUENCY_GUARD_ENABLED and product_total_seconds < FAST_MODE_MIN_CYCLE_SECONDS:
            return FAST_MODE_MIN_CYCLE_SECONDS - product_total_seconds + random.uniform(2, 5)
        return random.uniform(6, 10)
    if page_status == "success" and parse_status == "success" and next_mode == "stable":
        return random.uniform(10, 20)
    return random.uniform(10, 20)


def is_success_row(row: dict[str, str]) -> bool:
    return row.get("page_status") == "success" and row.get("parse_status") == "success"


def is_captcha_status(row: dict[str, str]) -> bool:
    return row.get("page_status") == "blocked_or_verify" and "明确验证码页面" in row.get("status_reason", "")


def is_login_required_status(row: dict[str, str]) -> bool:
    return row.get("page_status") == "login_required" and row.get("status_reason") == "明确登录页面"


def is_challenge_url(url: str) -> bool:
    url_lower = (url or "").lower()
    return "/risk/challenge" in url_lower or "captcha_type=" in url_lower


def wait_for_manual_captcha_resolution(session: dict[str, Any], product_id: str) -> tuple[str, float]:
    page = session["page"]
    start_time = time.monotonic()
    print("检测到明确人机验证页面。")
    print(f"商品ID：{product_id}")
    print("浏览器将保持打开。")
    print("浏览器保持打开，请手动完成验证码。")
    print("脚本正在等待验证通过，不需要在终端按 Enter。")

    while True:
        elapsed_seconds = time.monotonic() - start_time
        remaining_seconds = max(0, int(CAPTCHA_MANUAL_RESOLVE_TIMEOUT_SECONDS - elapsed_seconds))
        current_url = safe_page_url(page)
        print(f"剩余等待时间：{remaining_seconds} 秒")
        print(f"当前URL：{current_url}")

        if contains_login_page(current_url, safe_page_html(page), safe_page_text(page)):
            return "login_required", elapsed_seconds
        if not is_challenge_url(current_url):
            return "resolved", elapsed_seconds
        if elapsed_seconds >= CAPTCHA_MANUAL_RESOLVE_TIMEOUT_SECONDS:
            return "timeout", elapsed_seconds

        page.wait_for_timeout(int(CAPTCHA_MANUAL_POLL_INTERVAL_SECONDS * 1000))


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
    captcha_wait_used: bool = False,
    captcha_wait_seconds: float = 0.0,
) -> dict[str, str]:
    row["fetch_mode"] = fetch_mode
    row["attempt_count"] = str(attempt_count)
    row["captcha_wait_used"] = str(captcha_wait_used)
    row["captcha_wait_seconds"] = f"{captcha_wait_seconds:.2f}"
    row["recovery_used"] = str(recovery_used)
    row["manual_wait_seconds"] = f"{manual_wait_seconds:.2f}"
    row["fetch_seconds"] = f"{sum(parse_float(item.get('fetch_seconds')) for item in aggregate_rows):.2f}"
    row["save_seconds"] = f"{sum(parse_float(item.get('save_seconds')) for item in aggregate_rows):.2f}"
    row["parse_seconds"] = f"{sum(parse_float(item.get('parse_seconds')) for item in aggregate_rows):.2f}"
    row["product_total_seconds"] = (
        f"{sum(parse_float(item.get('product_total_seconds')) for item in aggregate_rows) + manual_wait_seconds:.2f}"
    )
    return row


def describe_page_status(page_status: str) -> str:
    descriptions = {
        "success": "success（成功进入商品详情页）",
        "timeout": "timeout（页面请求超时，可能是网络慢或页面加载太久）",
        "fetch_failed": "fetch_failed（未获取到足够商品主体信息）",
        "blocked_or_verify": "blocked_or_verify（进入明确验证码 / risk challenge 页面，本轮将停止）",
        "login_required": "login_required（进入 SHEIN 登录页，本轮将停止）",
    }
    return descriptions.get(page_status, f"{page_status}（未归类页面状态）")


def describe_parse_status(parse_status: str) -> str:
    descriptions = {
        "success": "success（Description 属性解析成功）",
        "skipped_due_to_page_status": "skipped_due_to_page_status（页面状态不是 success，跳过属性解析）",
        "description_not_found": "description_not_found（未找到 Description 属性）",
        "parse_failed": "parse_failed（Description 属性解析失败）",
    }
    return descriptions.get(parse_status, f"{parse_status}（未归类解析状态）")


def describe_fetch_mode(fetch_mode: str) -> str:
    if fetch_mode == "stable":
        return "stable = 稳定模式，加载更完整，主要用于第一个商品或恢复测试"
    if fetch_mode == "fast":
        return "fast = 快速模式，动态等待，控制频率后提速"
    if "stable" in fetch_mode:
        return f"{fetch_mode} = 含 stable 恢复/重试的采集模式"
    return f"{fetch_mode} = 当前采集模式"


def is_frequency_guard_sleep(row: dict[str, str]) -> bool:
    if row.get("frequency_guard_enabled") != "True":
        return False
    return (
        row.get("page_status") == "success"
        and row.get("parse_status") == "success"
        and row.get("fetch_mode") == "fast"
        and parse_float(row.get("product_total_seconds")) < FAST_MODE_MIN_CYCLE_SECONDS
        and parse_float(row.get("inter_sleep_seconds")) > 0
    )


def print_product_result(row: dict[str, str], product_index: int, total_products: int) -> None:
    """输出单个商品采集结果。"""
    key_count = count_key_fields(row)
    status_reason = row.get("status_reason", "")
    print(
        "timing: "
        f"current_mode={row['fetch_mode']}, "
        f"product_id={row['product_id']}, "
        f"attempt_count={row['attempt_count']}, "
        f"captcha_wait_used={row['captcha_wait_used']}, "
        f"captcha_wait_seconds={row['captcha_wait_seconds']}, "
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
    print("-" * 64)
    print(f"第 {product_index} / {total_products} 个商品")
    print(f"商品ID：{row['product_id']}")
    print(f"当前采集模式：{row['fetch_mode']}")
    print(f"模式说明：{describe_fetch_mode(row['fetch_mode'])}")
    print(f"页面状态：{describe_page_status(row['page_status'])}")
    print(f"解析状态：{describe_parse_status(row['parse_status'])}")
    print(f"Description 属性数量：{row['attribute_count']}")
    print(f"关键字段命中：{key_count} / {len(KEY_FIELDS_FOR_STATS)}")
    print(f"页面请求耗时：{row['fetch_seconds']} 秒")
    print(f"解析耗时：{row['parse_seconds']} 秒")
    print(f"单商品总耗时：{row['product_total_seconds']} 秒")
    print(f"下一个商品等待：{row['inter_sleep_seconds']} 秒")
    if row.get("frequency_guard_enabled") == "True":
        print(f"频率保护：已启用，目标约 1 分钟最多 {TARGET_PRODUCTS_PER_MINUTE} 个商品")
    if is_frequency_guard_sleep(row):
        print("频率保护生效：本商品采集较快，已补足等待时间，避免访问过快")
    hard_cap_status = "ProductHardCapExceeded" in status_reason or "fast 硬截止" in status_reason
    if hard_cap_status and parse_int(row.get("attribute_count")) >= FAST_MODE_MIN_ATTRIBUTE_COUNT:
        print("提示：本商品达到 fast 模式硬截止，但 Description 属性已加载完成，已保留为成功结果。")
    elif hard_cap_status:
        print("提示：本商品达到 fast 模式硬截止，且属性不足，记录为失败。")
    print(
        f"完成 product_id={row['product_id']}，"
        f"page_status={row['page_status']}，"
        f"parse_status={row['parse_status']}，"
        f"attribute_count={row['attribute_count']}，"
        f"关键字段={key_count}/{len(KEY_FIELDS_FOR_STATS)}"
    )


def main() -> None:
    """Run V2.9D-1B in local Playwright + KDL proxy mode only."""
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

    print("V2.9D1B local proxy test mode")
    print("=" * 64)
    print("session_type: local_proxy")
    print(f"proxy_configured: {PROXY_CONFIGURED}")
    print(f"fingerprint_mask_enabled: {FINGERPRINT_MASK_ENABLED}")
    print(f"user_agent_configured: {bool(USER_AGENT)}")
    print(f"sold candidates: {len(sold_candidates)}")
    print(f"planned products: {len(selected_products)}")

    results: list[dict[str, str]] = []
    run_start_time = time.monotonic()
    current_mode = "stable"
    stable_cooldown_remaining = 0
    consecutive_failures = 0
    consecutive_failure_max = 0
    consecutive_blocked_products = 0
    mode_switch_to_stable_count = 0
    mode_switch_to_fast_count = 0
    stopped_reason = ""
    proxy_preflight_status = "not_run"
    proxy_preflight_reason = ""
    session_type = "local_proxy"

    if not PROXY_CONFIGURED:
        proxy_preflight_reason = "KDL proxy is not configured"
        stopped_reason = proxy_preflight_reason
        print("Proxy is not configured. Set KDL_PROXY_SERVER / KDL_PROXY_USERNAME / KDL_PROXY_PASSWORD.")
    else:
        session: dict[str, Any] | None = None
        with sync_playwright() as playwright:
            try:
                session = create_local_proxy_browser_session(playwright)
                proxy_preflight_status, proxy_preflight_reason = run_proxy_preflight(session)
                print(f"proxy_preflight_status: {proxy_preflight_status}")
                print(f"proxy_preflight_reason: {proxy_preflight_reason}")
                if proxy_preflight_status != "success":
                    stopped_reason = proxy_preflight_reason
                    print("Proxy preflight failed; SHEIN collection will not start.")
                else:
                    for index, product in enumerate(selected_products, start=1):
                        product_id = normalize_text(product.get("product_id")) or extract_product_id_from_url(
                            normalize_text(product.get("product_url"))
                        )
                        print(f"\nCollecting {index}/{len(selected_products)}: product_id={product_id}")
                        if stable_cooldown_remaining > 0:
                            first_attempt_mode = "stable"
                            stable_cooldown_remaining -= 1
                        else:
                            first_attempt_mode = current_mode

                        first_row = fetch_and_parse_one_product(session, product, first_attempt_mode)
                        final_row = first_row
                        attempt_count = 1
                        recovery_used = False
                        manual_wait_seconds = 0.0
                        captcha_wait_used = False
                        captcha_wait_seconds = 0.0
                        captcha_wait_status = ""
                        aggregate_rows = [first_row]
                        final_fetch_mode = first_attempt_mode

                        if is_captcha_status(first_row):
                            captcha_wait_used = True
                            captcha_wait_status, manual_wait_seconds = wait_for_manual_captcha_resolution(
                                session,
                                product_id,
                            )
                            captcha_wait_seconds = manual_wait_seconds
                            if captcha_wait_status == "resolved":
                                recovery_used = True
                                print("验证码已通过。")
                                print("开始使用 stable_mode 重新采集当前商品。")
                                recovery_row = fetch_and_parse_one_product(session, product, "stable")
                                aggregate_rows.append(recovery_row)
                                final_row = recovery_row
                                attempt_count = 2
                                final_fetch_mode = "captcha_manual_resolved_stable_retry"
                            elif captcha_wait_status == "login_required":
                                recovery_used = True
                                print("检测到 SHEIN 账号登录页。")
                                print("当前会话已不适合继续采集。")
                                print("本轮采集立即停止。")
                                recovery_row = fetch_and_parse_one_product(session, product, "stable")
                                aggregate_rows.append(recovery_row)
                                final_row = recovery_row
                                attempt_count = 2
                                final_fetch_mode = "captcha_manual_resolved_stable_retry"
                        elif (
                            first_attempt_mode == "fast"
                            and should_stable_retry_due_to_empty_detail(first_row)
                            and attempt_count < MAX_ATTEMPTS_PER_PRODUCT
                        ):
                            recovery_used = True
                            mode_switch_to_stable_count += 1
                            stable_cooldown_remaining = LOCAL_FAST_EMPTY_DETAIL_STABLE_COOLDOWN
                            print("fast_mode returned empty details; retrying this product with stable_mode.")
                            recovery_row = fetch_and_parse_one_product(session, product, "stable")
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
                            captcha_wait_used=captcha_wait_used,
                            captcha_wait_seconds=captcha_wait_seconds,
                        )

                        next_mode = "stable" if stable_cooldown_remaining > 0 else "fast"
                        is_success = is_success_row(row)
                        if row.get("page_status") != "blocked_or_verify":
                            consecutive_blocked_products = 0
                        if is_success:
                            consecutive_failures = 0
                            session["success_count"] += 1
                        elif captcha_wait_used:
                            consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                            consecutive_failure_max = max(consecutive_failure_max, consecutive_failures)

                        inter_sleep_seconds = calculate_inter_sleep_seconds(row, next_mode)
                        row["stable_success_streak"] = "0"
                        row["consecutive_failures"] = str(consecutive_failures)
                        row["inter_sleep_seconds"] = f"{inter_sleep_seconds:.2f}"
                        results.append(row)
                        write_output_csv(results)
                        print_product_result(row, index, len(selected_products))
                        if captcha_wait_used:
                            print(f"captcha_wait_used: {row['captcha_wait_used']}")
                            print(f"captcha_wait_seconds: {row['captcha_wait_seconds']}")
                            print(f"attempt_count: {row['attempt_count']}")
                            print(f"fetch_mode: {row['fetch_mode']}")
                            print(f"page_status: {row['page_status']}")
                            print(f"parse_status: {row['parse_status']}")

                        if captcha_wait_status == "timeout":
                            stopped_reason = "captcha_manual_resolve_timeout"
                            print(f"stopped_reason: {stopped_reason}")
                            break

                        if captcha_wait_status == "resolved" and is_captcha_status(row):
                            stopped_reason = "captcha_manual_recovery_failed"
                            print(f"stopped_reason: {stopped_reason}")
                            break

                        if captcha_wait_status == "login_required":
                            stopped_reason = "login_required_stop"
                            print("已保存 CSV、summary 和 debug 文件。")
                            print(f"stopped_reason: {stopped_reason}")
                            break

                        if STOP_ON_LOGIN_REQUIRED and is_login_required_status(row):
                            stopped_reason = "login_required_stop"
                            print("检测到 SHEIN 账号登录页。")
                            print("当前会话已不适合继续采集。")
                            print("本轮采集立即停止。")
                            print("已保存 CSV、summary 和 debug 文件。")
                            print(f"stopped_reason: {stopped_reason}")
                            break

                        if STOP_ON_CAPTCHA and consecutive_blocked_products >= MAX_CONSECUTIVE_BLOCKED_PRODUCTS:
                            stopped_reason = (
                                f"{MAX_CONSECUTIVE_BLOCKED_PRODUCTS} consecutive explicit captcha pages; stopping"
                            )
                            print(stopped_reason)
                            break

                        if consecutive_failures >= 5:
                            stopped_reason = "Consecutive failures reached 5; collection stopped automatically"
                            print(stopped_reason)
                            break

                        if index < len(selected_products):
                            print(f"Waiting {inter_sleep_seconds} seconds before the next product...")
                            time.sleep(inter_sleep_seconds)
                        if current_mode != next_mode:
                            mode_switch_to_fast_count += 1
                        current_mode = next_mode
            except Exception as exc:  # noqa: BLE001 - write summary instead of entering collection.
                proxy_preflight_status = "failed"
                proxy_preflight_reason = safe_proxy_failure_reason(exc)
                stopped_reason = proxy_preflight_reason
                print("Local proxy browser startup or preflight failed; SHEIN collection will not start.")
            finally:
                close_browser_session(session)

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
        proxy_preflight_status=proxy_preflight_status,
        proxy_preflight_reason=proxy_preflight_reason,
        session_type=session_type,
    )

    print("\nV2.9D1B 50-product detail collection complete")
    print("=" * 64)
    print(f"sold candidates: {len(sold_candidates)}")
    print(f"planned products: {len(selected_products)}")
    print(f"page_status = success count: {success_count}")
    print(f"parse_status = success count: {parse_success_count}")
    print(f"blocked_or_verify count: {summary_row['blocked_or_verify_count']}")
    print(f"captcha_wait_used_count: {summary_row['captcha_wait_used_count']}")
    print(f"captcha_recovery_success_count: {summary_row['captcha_recovery_success_count']}")
    print(f"captcha_recovery_failed_count: {summary_row['captcha_recovery_failed_count']}")
    print(f"average_captcha_wait_seconds: {summary_row['average_captcha_wait_seconds']}")
    print(f"login_required count: {summary_row['login_required_count']}")
    print(f"connection_closed count: {summary_row['connection_closed_count']}")
    print(f"timeout count: {summary_row['timeout_count']}")
    print(f"fetch_failed count: {summary_row['fetch_failed_count']}")
    print(f"product_unavailable count: {summary_row['product_unavailable_count']}")
    print(f"not_found count: {summary_row['not_found_count']}")
    print(f"session_type: {summary_row['session_type']}")
    print(f"proxy_configured: {summary_row['proxy_configured']}")
    print(f"fingerprint_mask_enabled: {summary_row['fingerprint_mask_enabled']}")
    print(f"user_agent_configured: {summary_row['user_agent_configured']}")
    print(f"proxy_preflight_status: {summary_row['proxy_preflight_status']}")
    print(f"proxy_preflight_reason: {summary_row['proxy_preflight_reason']}")
    print(f"detail_direct_mode_enabled: {summary_row['detail_direct_mode_enabled']}")
    print(f"category_preflight_required: {summary_row['category_preflight_required']}")
    print("max_consecutive_blocked_products: " f"{summary_row['max_consecutive_blocked_products']}")
    print(f"stop_on_login_required: {summary_row['stop_on_login_required']}")
    print(f"stop_on_captcha: {summary_row['stop_on_captcha']}")
    if selected_products:
        success_rate_value = success_count / len(selected_products)
        if success_rate_value < V29C_REFERENCE_SUCCESS_RATE - 0.05:
            print("Notice: success_rate is below the V2.9C reference; network or pacing pressure may exist.")
    for row in results:
        key_count = count_key_fields(row)
        print(
            f"product_id={row['product_id']}, "
            f"attribute_count={row['attribute_count']}, "
            f"key_fields={key_count}/{len(KEY_FIELDS_FOR_STATS)}"
        )
    print(f"CSV path: {OUTPUT_CSV_PATH}")
    print(f"Debug dir: {DEBUG_DIR}")
    print(f"Summary CSV path: {SUMMARY_CSV_PATH}")

if __name__ == "__main__":
    main()
