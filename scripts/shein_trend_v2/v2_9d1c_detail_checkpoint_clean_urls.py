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

try:
    from cloakbrowser import launch as cloak_launch
except ImportError:
    cloak_launch = None

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

INPUT_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_7b_products_10_pages_merged_clean_urls.csv"
OUTPUT_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d1c_detail_attributes_checkpoint_clean_urls.csv"
SUMMARY_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d1c_detail_summary_checkpoint_clean_urls.csv"
FAILED_RETRY_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d1c_failed_retry_checkpoint_clean_urls.csv"
PREFLIGHT_MATRIX_CSV_PATH = PROJECT_ROOT / "data" / "output" / "v2_9d1b_preflight_matrix.csv"
DEBUG_DIR = PROJECT_ROOT / "data" / "debug" / "v2_9d1c_detail_checkpoint_clean_urls"
BATCH_SIZE = 10
BATCH_SLEEP_MIN_SECONDS = 480
BATCH_SLEEP_MAX_SECONDS = 720
UNATTENDED_LOOP_ENABLED = False
MAX_CONSECUTIVE_FETCH_FAILED_PRODUCTS = 3
MAX_CONSECUTIVE_EMPTY_ATTRIBUTE_PRODUCTS = 3
BROWSER_SESSION_MODE = "cloakbrowser"
CLOAK_BROWSER_PROFILE_NAME = "Owner avatar"
CLOAK_HUMANIZE_ENABLED = True
BROWSERLEAKS_BEFORE_COLLECTION_ENABLED = True
BROWSERLEAKS_URL = "https://browserleaks.com/ip"
BROWSERLEAKS_OBSERVE_SECONDS = 300
SHEIN_HOME_WARMUP_ENABLED = True
SHEIN_HOME_WARMUP_SECONDS = 180
SHEIN_HOME_URL = "https://sg.shein.com/"
SHEIN_HOME_CAPTCHA_MANUAL_TIMEOUT_SECONDS = 300
DETAIL_CAPTCHA_MANUAL_TIMEOUT_SECONDS = 300
SHEIN_HOME_AFTER_VERIFY_STABLE_MIN_SECONDS = 15
SHEIN_HOME_AFTER_VERIFY_STABLE_MAX_SECONDS = 20
SHEIN_HOME_REQUIRE_ENTER_CONFIRM = False
CAPTCHA_COUNTDOWN_PRINT_INTERVAL_SECONDS = 5
VERIFY_STABLE_PRINT_INTERVAL_SECONDS = 5
WARMUP_COUNTDOWN_PRINT_INTERVAL_SECONDS = 5
V29C_REFERENCE_SUCCESS_RATE = 0.95
FAST_MODE_MIN_CYCLE_SECONDS = 20
FAST_MODE_MIN_PAGE_SECONDS = 8
FAST_MODE_MAX_READY_LOOPS = 15
FAST_MODE_READY_INTERVAL_MS = 2000
FAST_MODE_MIN_ATTRIBUTE_COUNT = 5
FAST_HUMAN_DWELL_ENABLED = True
DETAIL_PAGE_DWELL_MIN_SECONDS = 13
DETAIL_PAGE_DWELL_MAX_SECONDS = 19
BETWEEN_PRODUCT_SLEEP_MIN_SECONDS = 5
BETWEEN_PRODUCT_SLEEP_MAX_SECONDS = 10
DESCRIPTION_EMPTY_EXTRA_WAIT_ENABLED = True
DESCRIPTION_EMPTY_EXTRA_WAIT_MIN_SECONDS = 10
DESCRIPTION_EMPTY_EXTRA_WAIT_MAX_SECONDS = 15
DESCRIPTION_EMPTY_EXTRA_SCROLL_TIMES = 3
DESCRIPTION_EMPTY_STABLE_RETRY_ENABLED = True
PRODUCT_CREATE_DATE_FROM_SKU_ENABLED = True
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
STOP_REQUESTED = False
ACTIVE_SESSION: dict[str, Any] | None = None


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
    "product_create_date",
    "product_create_date_digits",
    "product_create_date_parse_status",
    "product_create_date_parse_reason",
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
    "detail_dwell_seconds",
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

D1C_SUMMARY_FIELDS = [
    "run_mode",
    "input_csv_path",
    "output_csv_path",
    "total_candidates",
    "already_success_count",
    "remaining_count_before_batch",
    "batch_size",
    "current_batch_planned",
    "current_batch_success_count",
    "current_batch_blocked_count",
    "current_batch_login_required_count",
    "current_batch_fetch_failed_count",
    "current_batch_empty_attribute_count",
    "current_batch_start_time",
    "current_batch_end_time",
    "batch_elapsed_seconds",
    "sleep_seconds",
    "stopped_reason",
    "clean_url_validation_passed",
    "proxy_preflight_status",
    "proxy_preflight_reason",
    "session_type",
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
    FAILED_RETRY_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def interruptible_sleep(
    total_seconds: int | float,
    label: str = "休眠",
    print_interval: int = 5,
) -> None:
    """Sleep in one-second steps so Ctrl+C is handled immediately."""
    duration = max(0.0, float(total_seconds))
    deadline = time.monotonic() + duration
    last_printed: int | None = None

    while True:
        if STOP_REQUESTED:
            raise KeyboardInterrupt
        remaining = max(0.0, deadline - time.monotonic())
        remaining_whole = int(math.ceil(remaining))
        should_print = (
            bool(label)
            and (
                last_printed is None
                or remaining_whole == 0
                or remaining_whole % max(1, print_interval) == 0
            )
        )
        if should_print and remaining_whole != last_printed:
            print(f"{label}：剩余 {remaining_whole} 秒")
            last_printed = remaining_whole
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


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


def build_kdl_proxy_url() -> str:
    """Build the proxy URL format used by the validated CloakBrowser flow."""
    safe_server = PROXY_SERVER
    if safe_server.startswith("http://"):
        safe_server = safe_server.removeprefix("http://")
    elif safe_server.startswith("https://"):
        safe_server = safe_server.removeprefix("https://")
    return f"http://{PROXY_USERNAME}:{PROXY_PASSWORD}@{safe_server}"


def create_cloak_proxy_browser_session() -> dict[str, Any]:
    """Launch the Owner avatar CloakBrowser identity with the KDL proxy."""
    if BROWSER_SESSION_MODE != "cloakbrowser":
        raise RuntimeError(f"不支持的 BROWSER_SESSION_MODE：{BROWSER_SESSION_MODE}")
    if cloak_launch is None:
        raise RuntimeError("未安装 cloakbrowser，请先执行：python -m pip install cloakbrowser")
    if not PROXY_CONFIGURED:
        raise RuntimeError(
            "KDL proxy is not configured. Set KDL_PROXY_SERVER, "
            "KDL_PROXY_USERNAME, and KDL_PROXY_PASSWORD."
        )

    proxy_url = build_kdl_proxy_url()
    try:
        browser = cloak_launch(
            headless=False,
            proxy=proxy_url,
            humanize=CLOAK_HUMANIZE_ENABLED,
        )
    except TypeError:
        browser = cloak_launch(
            headless=False,
            proxy={
                "server": PROXY_SERVER,
                "username": PROXY_USERNAME,
                "password": PROXY_PASSWORD,
            },
            humanize=CLOAK_HUMANIZE_ENABLED,
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
    return {
        "browser": browser,
        "context": context,
        "browserleaks_page": None,
        "shein_page": None,
        "page": None,
        "started_at": time.monotonic(),
        "success_count": 0,
        "session_type": "cloakbrowser",
        "profile_name": CLOAK_BROWSER_PROFILE_NAME,
    }


def close_browser_session(session: dict[str, Any] | None) -> None:
    """Best-effort cleanup for all session pages, context, and browser."""
    if not session:
        return
    closed_page_ids: set[int] = set()
    for page_key in (
        "browserleaks_page",
        "observation_page",
        "warmup_page",
        "shein_page",
        "detail_page",
        "page",
        "preflight_page",
    ):
        page = session.get(page_key)
        if not page or id(page) in closed_page_ids:
            continue
        try:
            page.close()
        except Exception:
            pass
        closed_page_ids.add(id(page))
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


def infer_product_create_date_from_sku(sku: Any) -> dict[str, str]:
    """根据详情页 SKU 推断产品创建日期。"""
    result = {
        "product_create_date": "",
        "product_create_date_digits": "",
        "product_create_date_parse_status": "failed",
        "product_create_date_parse_reason": "",
    }

    if not PRODUCT_CREATE_DATE_FROM_SKU_ENABLED:
        result["product_create_date_parse_status"] = "disabled"
        result["product_create_date_parse_reason"] = "产品创建日期解析未启用"
        return result

    sku_text = normalize_text(sku)
    if not sku_text:
        result["product_create_date_parse_reason"] = "详情页 SKU 为空"
        return result

    match = re.match(r"^[A-Za-z]+(\d{6})", sku_text)
    if not match:
        result["product_create_date_parse_reason"] = (
            f"SKU 未匹配到字母前缀后的 6 位日期数字：{sku_text}"
        )
        return result

    digits = match.group(1)
    result["product_create_date_digits"] = digits

    try:
        year = 2000 + int(digits[0:2])
        month = int(digits[2:4])
        day = int(digits[4:6])
        create_dt = datetime(year, month, day)
    except ValueError:
        result["product_create_date_parse_reason"] = f"SKU 日期数字不是合法日期：{digits}"
        return result

    result["product_create_date"] = create_dt.date().isoformat()
    result["product_create_date_parse_status"] = "success"
    result["product_create_date_parse_reason"] = (
        "SKU 前 6 位数字按 YYMMDD 成功解析为产品创建日期"
    )
    return result


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
    """读取 V2.7B URL 清洗增强主表。"""
    if not INPUT_CSV_PATH.exists():
        raise FileNotFoundError(f"输入文件不存在：{INPUT_CSV_PATH}")
    with INPUT_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def validate_clean_product_urls_or_raise(products: list[dict[str, str]]) -> None:
    """强校验输入文件名和所有商品的 Clean URL。"""
    expected_name = "v2_7b_products_10_pages_merged_clean_urls.csv"
    if INPUT_CSV_PATH.name != expected_name:
        raise RuntimeError(
            f"INPUT_CSV_PATH 必须指向 {expected_name}，当前为：{INPUT_CSV_PATH}"
        )

    mismatched_clean_urls: list[tuple[str, str, str]] = []
    urls_with_query: list[tuple[str, str]] = []
    for product in products:
        product_id = normalize_text(product.get("product_id"))
        product_url = normalize_text(product.get("product_url"))
        product_url_clean = normalize_text(product.get("product_url_clean"))
        if "?" in product_url:
            urls_with_query.append((product_id, product_url))
        if product_url_clean and product_url != product_url_clean:
            mismatched_clean_urls.append((product_id, product_url, product_url_clean))

    for product_id, product_url, product_url_clean in mismatched_clean_urls:
        print(
            "warning：product_url 与 product_url_clean 不一致，仍以 product_url 采集。"
            f" product_id={product_id}, product_url={product_url}, "
            f"product_url_clean={product_url_clean}"
        )

    if urls_with_query:
        for product_id, product_url in urls_with_query:
            print(
                "Clean URL 强校验失败："
                f"product_id={product_id}, product_url={product_url}"
            )
        raise RuntimeError(
            f"发现 {len(urls_with_query)} 个包含 ? 的 product_url，已停止运行"
        )

    print("Clean URL 强校验通过：所有 product_url 均不包含 query 参数。")


def select_sold_products(products: list[dict[str, str]]) -> list[dict[str, str]]:
    """筛选全部真实 sold 商品，并沿用 D1B 排序。"""
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
    return candidates


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


def scroll_detail_page(browser_page: Any, product_start_time: float, fetch_mode: str) -> str:
    """在 stable 商品硬截止内轻量滚动，触发详情属性加载。"""
    if is_detail_captcha_page(browser_page):
        print("检测到商品详情页验证码，停止当前页面等待，进入人工验证码流程。", flush=True)
        return "detail_captcha_detected"
    if not wait_with_product_hard_cap(browser_page, product_start_time, fetch_mode, 3000):
        return "hard_cap_exceeded"
    for _ in range(3):
        if is_detail_captcha_page(browser_page):
            print("检测到商品详情页验证码，停止当前页面等待，进入人工验证码流程。", flush=True)
            return "detail_captcha_detected"
        final_url = safe_page_url(browser_page)
        if is_early_escape_url(final_url):
            print(f"检测到提前逃生 URL，停止 stable 等待：{final_url}")
            return "not_ready"
        if is_product_hard_cap_exceeded(product_start_time, fetch_mode):
            print(f"{fetch_mode} 商品达到单商品硬截止，停止等待。")
            return "hard_cap_exceeded"
        browser_page.mouse.wheel(0, 1000)
        if not wait_with_product_hard_cap(browser_page, product_start_time, fetch_mode, 1000):
            return "hard_cap_exceeded"
    return "ready"


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


def is_detail_captcha_page(page: Any) -> bool:
    """Detect a real detail captcha without classifying a healthy product page."""
    final_url = safe_page_url(page)
    visible_text = safe_page_text(page)
    html_text = safe_page_html(page)
    if is_challenge_url(final_url) or contains_visible_captcha_page(visible_text):
        return True

    html_lower = html_text.lower()
    visible_lower = visible_text.lower()
    has_captcha_component = any(keyword.lower() in html_lower for keyword in CAPTCHA_HTML_KEYWORDS)
    has_verification_context = any(
        keyword in visible_lower
        for keyword in ("verify", "human", "robot", "captcha", "security verification")
    )
    body_signal_count = count_product_body_signals(html_text, visible_text) if html_text else 0
    return has_captcha_component and has_verification_context and body_signal_count < 4


def wait_for_description_attributes(page: Any, product_id: str) -> tuple[int, float]:
    """页面主体已加载但 Description 属性为空时，追加等待和滚动。"""
    wait_seconds = random.uniform(
        DESCRIPTION_EMPTY_EXTRA_WAIT_MIN_SECONDS,
        DESCRIPTION_EMPTY_EXTRA_WAIT_MAX_SECONDS,
    )
    start_time = time.monotonic()
    deadline = start_time + wait_seconds

    print(
        f"商品 {product_id} 页面主体已加载，但 Description 属性为空，"
        f"追加等待 {wait_seconds:.2f} 秒。",
        flush=True,
    )

    for scroll_index in range(1, DESCRIPTION_EMPTY_EXTRA_SCROLL_TIMES + 1):
        if is_detail_captcha_page(page):
            print("追加等待期间检测到商品详情页验证码，停止 Description 等待。", flush=True)
            break

        html_text = safe_page_html(page)
        attribute_count = len(extract_description_attributes(html_text)) if html_text else 0
        print(
            f"追加滚动检查 Description：第 {scroll_index} 次，"
            f"attribute_count={attribute_count}",
            flush=True,
        )
        if attribute_count > 0:
            actual_wait_seconds = time.monotonic() - start_time
            print(
                f"商品 {product_id} Description 追加等待完成，"
                f"attribute_count={attribute_count}",
                flush=True,
            )
            return attribute_count, actual_wait_seconds

        try:
            page.mouse.wheel(0, random.randint(600, 1000))
        except Exception:
            pass

        remaining_seconds = max(0.0, deadline - time.monotonic())
        if remaining_seconds <= 0:
            break
        pause_seconds = min(
            remaining_seconds,
            max(1.0, wait_seconds / DESCRIPTION_EMPTY_EXTRA_SCROLL_TIMES),
        )
        interruptible_sleep(
            pause_seconds,
            label="Description 追加等待中",
            print_interval=5,
        )

    html_text = safe_page_html(page)
    attribute_count = len(extract_description_attributes(html_text)) if html_text else 0
    actual_wait_seconds = time.monotonic() - start_time
    print(
        f"商品 {product_id} Description 追加等待完成，"
        f"attribute_count={attribute_count}",
        flush=True,
    )
    return attribute_count, actual_wait_seconds


def smart_wait_detail_ready(browser_page: Any, product_start_time: float, fetch_mode: str) -> str:
    """Fast-mode dynamic wait: stop once product signals or Description attributes are ready."""
    start_time = time.monotonic()
    browser_page.wait_for_timeout(1000)
    min_page_seconds = FAST_MODE_MIN_PAGE_SECONDS
    min_attribute_count = FAST_MODE_MIN_ATTRIBUTE_COUNT

    for _ in range(FAST_MODE_MAX_READY_LOOPS):
        if is_detail_captcha_page(browser_page):
            print("检测到商品详情页验证码，停止当前页面等待，进入人工验证码流程。", flush=True)
            return "detail_captcha_detected"
        final_url = safe_page_url(browser_page)
        if is_early_escape_url(final_url):
            print(f"检测到提前逃生 URL，停止 fast 等待：{final_url}")
            return "not_ready"
        if is_product_hard_cap_exceeded(product_start_time, fetch_mode):
            print(f"{fetch_mode} 商品达到单商品硬截止，停止等待。")
            return "hard_cap_exceeded"

        html_text = safe_page_html(browser_page)
        visible_text = safe_page_text(browser_page)
        if contains_visible_captcha_page(visible_text):
            print("检测到商品详情页验证码，停止当前页面等待，进入人工验证码流程。", flush=True)
            return "detail_captcha_detected"

        elapsed_seconds = time.monotonic() - start_time
        body_signal_count = count_product_body_signals(html_text, visible_text)
        attribute_count = len(extract_description_attributes(html_text))
        if elapsed_seconds >= min_page_seconds:
            if attribute_count >= min_attribute_count:
                return "ready"
            if body_signal_count >= 3 and attribute_count > 0:
                return "ready"
            if body_signal_count >= 4:
                return "ready"

        browser_page.mouse.wheel(0, 800)
        if not wait_with_product_hard_cap(
            browser_page,
            product_start_time,
            fetch_mode,
            FAST_MODE_READY_INTERVAL_MS,
        ):
            return "hard_cap_exceeded"
    return "not_ready"


def human_like_detail_page_dwell(browser_page: Any, product_id: str) -> float:
    """Pause and lightly scroll a healthy FAST detail page like a human reader."""
    dwell_seconds = random.uniform(
        DETAIL_PAGE_DWELL_MIN_SECONDS,
        DETAIL_PAGE_DWELL_MAX_SECONDS,
    )
    scroll_target = random.randint(2, 4)
    scroll_count = 0
    start_time = time.monotonic()
    deadline = start_time + dwell_seconds

    for scroll_index in range(scroll_target):
        if is_detail_captcha_page(browser_page):
            break
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            break

        browser_page.mouse.wheel(0, random.randint(400, 800))
        scroll_count += 1
        remaining_scrolls = scroll_target - scroll_index
        pause_seconds = min(
            remaining_seconds,
            random.uniform(2.0, max(2.0, remaining_seconds / remaining_scrolls)),
        )
        interruptible_sleep(pause_seconds, label="", print_interval=5)

    remaining_seconds = deadline - time.monotonic()
    if remaining_seconds > 0 and not is_detail_captcha_page(browser_page):
        interruptible_sleep(remaining_seconds, label="", print_interval=5)

    actual_dwell_seconds = time.monotonic() - start_time
    print(f"商品 {product_id} 详情页人工浏览停留 {actual_dwell_seconds:.2f} 秒。", flush=True)
    print(f"轻量滚动 {scroll_count} 次，用于模拟查看详情页信息。", flush=True)
    return actual_dwell_seconds


def fetch_detail_page(
    session: dict[str, Any],
    product_url: str,
    fetch_mode: str,
    product_id: str = "",
) -> dict[str, str]:
    """Use the current local Playwright page to visit the product detail page."""
    page = session["page"]
    start_time = time.monotonic()
    detail_dwell_seconds = 0.0

    try:
        try:
            page.goto(
                product_url,
                wait_until="domcontentloaded",
                timeout=FAST_DETAIL_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            if is_detail_captcha_page(page):
                print("检测到商品详情页验证码，停止当前页面等待，进入人工验证码流程。", flush=True)
                return {
                    "html_text": safe_page_html(page),
                    "visible_text": safe_page_text(page),
                    "final_url": safe_page_url(page) or product_url,
                    "error_text": "DetailCaptchaDetected",
                    "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
                    "detail_dwell_seconds": "0.00",
                    "detail_captcha_detected": "True",
                }
            raise

        current_url = safe_page_url(page)
        if is_detail_captcha_page(page):
            print("检测到商品详情页验证码，停止当前页面等待，进入人工验证码流程。", flush=True)
            return {
                "html_text": safe_page_html(page),
                "visible_text": safe_page_text(page),
                "final_url": current_url,
                "error_text": "DetailCaptchaDetected",
                "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
                "detail_dwell_seconds": "0.00",
                "detail_captcha_detected": "True",
            }

        if is_product_hard_cap_exceeded(start_time, fetch_mode):
            return {
                "html_text": safe_page_html(page),
                "visible_text": safe_page_text(page),
                "final_url": safe_page_url(page) or product_url,
                "error_text": f"ProductHardCapExceeded: {fetch_mode} 商品采集超过硬截止",
                "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
                "detail_dwell_seconds": "0.00",
                "detail_captcha_detected": "False",
            }

        if fetch_mode == "stable":
            wait_status = scroll_detail_page(page, start_time, fetch_mode)
        else:
            wait_status = smart_wait_detail_ready(page, start_time, fetch_mode)

        if wait_status == "detail_captcha_detected" or is_detail_captcha_page(page):
            return {
                "html_text": safe_page_html(page),
                "visible_text": safe_page_text(page),
                "final_url": safe_page_url(page) or product_url,
                "error_text": "DetailCaptchaDetected",
                "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
                "detail_dwell_seconds": "0.00",
                "detail_captcha_detected": "True",
            }

        if fetch_mode == "fast":
            current_url = safe_page_url(page)
            current_html = safe_page_html(page)
            current_visible_text = safe_page_text(page)
            page_is_healthy = (
                not is_challenge_url(current_url)
                and not contains_login_page(current_url, current_html, current_visible_text)
                and not contains_visible_captcha_page(current_visible_text)
            )
            if FAST_HUMAN_DWELL_ENABLED and page_is_healthy:
                detail_dwell_seconds = human_like_detail_page_dwell(page, product_id)

        if is_detail_captcha_page(page):
            print("检测到商品详情页验证码，停止当前页面等待，进入人工验证码流程。", flush=True)
            return {
                "html_text": safe_page_html(page),
                "visible_text": safe_page_text(page),
                "final_url": safe_page_url(page) or product_url,
                "error_text": "DetailCaptchaDetected",
                "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
                "detail_dwell_seconds": f"{detail_dwell_seconds:.2f}",
                "detail_captcha_detected": "True",
            }

        if is_product_hard_cap_exceeded(start_time, fetch_mode):
            return {
                "html_text": safe_page_html(page),
                "visible_text": safe_page_text(page),
                "final_url": safe_page_url(page) or product_url,
                "error_text": f"ProductHardCapExceeded: {fetch_mode} 商品采集超过硬截止",
                "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
                "detail_dwell_seconds": f"{detail_dwell_seconds:.2f}",
                "detail_captcha_detected": "False",
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
            "detail_dwell_seconds": f"{detail_dwell_seconds:.2f}",
            "detail_captcha_detected": "False",
        }
    except PlaywrightTimeoutError as exc:
        if is_detail_captcha_page(page):
            print("检测到商品详情页验证码，停止当前页面等待，进入人工验证码流程。", flush=True)
            return {
                "html_text": safe_page_html(page),
                "visible_text": safe_page_text(page),
                "final_url": safe_page_url(page) or product_url,
                "error_text": "DetailCaptchaDetected",
                "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
                "detail_dwell_seconds": "0.00",
                "detail_captcha_detected": "True",
            }
        return {
            "html_text": safe_page_html(page),
            "visible_text": safe_page_text(page) or f"TimeoutError: {exc}",
            "final_url": safe_page_url(page) or product_url,
            "error_text": f"TimeoutError: {exc}",
            "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
            "detail_dwell_seconds": f"{detail_dwell_seconds:.2f}",
            "detail_captcha_detected": "False",
        }
    except Exception as exc:
        return {
            "html_text": safe_page_html(page),
            "visible_text": safe_page_text(page) or f"{type(exc).__name__}: {exc}",
            "final_url": safe_page_url(page) or product_url,
            "error_text": f"{type(exc).__name__}: {exc}",
            "fetch_seconds": f"{time.monotonic() - start_time:.2f}",
            "detail_dwell_seconds": f"{detail_dwell_seconds:.2f}",
            "detail_captcha_detected": "False",
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
    """Check api.ipify.org on a disposable page without touching SHEIN pages."""
    preflight_page = None
    try:
        preflight_page = session["context"].new_page()
        session["preflight_page"] = preflight_page
        preflight_page.goto(
            "https://api.ipify.org",
            wait_until="domcontentloaded",
            timeout=PROXY_PREFLIGHT_TIMEOUT_MS,
        )
        body_text = normalize_text(safe_page_text(preflight_page))
        if body_text and re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", body_text):
            return "success", "api_ipify_success"
        if body_text:
            return "failed", "api_ipify_non_ip_response"
        return "failed", "api_ipify_empty_response"
    except PlaywrightTimeoutError:
        return "failed", "TimeoutError: api_ipify_timeout"
    except Exception as exc:  # noqa: BLE001 - only a safe summary is written.
        return "failed", safe_proxy_failure_reason(exc)
    finally:
        if preflight_page:
            try:
                preflight_page.close()
            except Exception:
                pass
        session["preflight_page"] = None


def open_browserleaks_before_collection(session: dict[str, Any]) -> None:
    """Open and preserve a diagnostic page without changing session['page']."""
    try:
        diagnostic_page = session["context"].new_page()
        session["browserleaks_page"] = diagnostic_page
        diagnostic_page.goto(
            BROWSERLEAKS_URL,
            wait_until="domcontentloaded",
            timeout=PROXY_PREFLIGHT_TIMEOUT_MS,
        )
        print("BrowserLeaks 已在当前采集用浏览器会话中打开。", flush=True)
        print(f"观察页：{BROWSERLEAKS_URL}", flush=True)
        print("请人工检查 IP、WebRTC、DNS、IPv6、Timezone、User-Agent。", flush=True)
        print("BrowserLeaks 页面将保持打开，不会作为 SHEIN 采集页面复用。", flush=True)
    except Exception as exc:  # noqa: BLE001 - diagnostics must not block collection.
        print(
            "warning：BrowserLeaks 观察页打开失败，将继续后续流程："
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


def is_shein_challenge_page(page: Any) -> bool:
    return is_challenge_url(safe_page_url(page)) or contains_visible_captcha_page(
        safe_page_text(page)
    )


def count_shein_home_signals(html_text: str, visible_text: str, final_url: str) -> int:
    """Count independent signals that indicate a usable SHEIN home page."""
    combined_text = f"{visible_text} {html_text}".lower()
    final_url_lower = (final_url or "").lower()
    signals = [
        "sg.shein.com" in final_url_lower,
        "shein" in combined_text,
        "categories" in combined_text,
        "women clothing" in combined_text,
        "new in" in combined_text,
        "sale" in combined_text,
        any(marker in combined_text for marker in ("search", "type=\"search\"", "role=\"search\"")),
        "just for you" in combined_text,
    ]
    return sum(signals)


def is_shein_home_ready(page: Any) -> bool:
    """Require a non-challenge, non-login home page with at least two home signals."""
    final_url = safe_page_url(page)
    visible_text = safe_page_text(page)
    html_text = safe_page_html(page)
    if is_challenge_url(final_url) or contains_visible_captcha_page(visible_text):
        return False
    if contains_login_page(final_url, html_text, visible_text):
        return False
    return count_shein_home_signals(html_text, visible_text, final_url) >= 2


def wait_for_manual_captcha_clear(
    page: Any,
    label: str,
    timeout_seconds: int = 300,
) -> tuple[str, str]:
    """Wait without collecting until a manually solved captcha is stably cleared."""
    print(f"检测到 {label} 验证码页面。", flush=True)
    print("请在浏览器中人工完成验证。", flush=True)
    print("脚本正在等待验证码通过，不会继续采集。", flush=True)
    deadline = time.monotonic() + timeout_seconds

    while True:
        remaining_seconds = max(0, int(math.ceil(deadline - time.monotonic())))
        print(f"{label} 验证码等待中：剩余 {remaining_seconds} 秒", flush=True)

        final_url = safe_page_url(page)
        visible_text = safe_page_text(page)
        html_text = safe_page_html(page)
        cleared = (
            not is_challenge_url(final_url)
            and not contains_visible_captcha_page(visible_text)
            and not contains_login_page(final_url, html_text, visible_text)
        )
        if label == "SHEIN 首页":
            cleared = cleared and is_shein_home_ready(page)
        if cleared:
            print(f"{label} 验证码已通过。", flush=True)
            return "cleared", f"{label}_captcha_cleared"
        if remaining_seconds <= 0:
            print(
                f"{label} 验证码 {timeout_seconds} 秒内未通过，结束当前采集批次。",
                flush=True,
            )
            return "timeout", f"{label}_captcha_timeout_{timeout_seconds}_seconds"

        interruptible_sleep(
            min(CAPTCHA_COUNTDOWN_PRINT_INTERVAL_SECONDS, remaining_seconds),
            label="",
            print_interval=CAPTCHA_COUNTDOWN_PRINT_INTERVAL_SECONDS,
        )


def is_browser_session_usable(session: dict[str, Any]) -> bool:
    """Return False when the visible browser or SHEIN page was closed manually."""
    browser = session.get("browser")
    shein_page = session.get("shein_page")
    try:
        if browser is not None and not browser.is_connected():
            return False
    except Exception:
        return False
    try:
        if shein_page is not None and shein_page.is_closed():
            return False
    except Exception:
        return False
    return True


def ensure_shein_collection_page(session: dict[str, Any]) -> tuple[str, str]:
    """Open, verify, and preserve the SHEIN home page without using it for collection."""
    shein_page = session["context"].new_page()
    session["shein_page"] = shein_page
    if RESOURCE_BLOCKING_ENABLED:
        install_resource_blocking(shein_page)

    try:
        shein_page.goto(
            SHEIN_HOME_URL,
            wait_until="domcontentloaded",
            timeout=STABLE_DETAIL_TIMEOUT_MS,
        )
    except Exception as exc:  # noqa: BLE001 - keep the visible page available for manual recovery.
        print(f"SHEIN 首页打开提示：{type(exc).__name__}: {exc}", flush=True)

    print("SHEIN 首页已打开。", flush=True)
    print("如果页面出现验证码，请先在浏览器中人工完成验证。", flush=True)
    print("正式采集不会在验证码通过前开始。", flush=True)

    if is_shein_challenge_page(shein_page):
        captcha_status, _ = wait_for_manual_captcha_clear(
            shein_page,
            label="SHEIN 首页",
            timeout_seconds=SHEIN_HOME_CAPTCHA_MANUAL_TIMEOUT_SECONDS,
        )
        if captcha_status == "timeout":
            return "captcha_timeout", "shein_home_captcha_timeout_300_seconds"

    ready_deadline = time.monotonic() + SHEIN_HOME_CAPTCHA_MANUAL_TIMEOUT_SECONDS
    while not is_shein_home_ready(shein_page):
        if not is_browser_session_usable(session):
            return "browser_closed", "cloakbrowser_or_shein_page_closed_during_warmup"
        if is_shein_challenge_page(shein_page):
            captcha_status, _ = wait_for_manual_captcha_clear(
                shein_page,
                label="SHEIN 首页",
                timeout_seconds=SHEIN_HOME_CAPTCHA_MANUAL_TIMEOUT_SECONDS,
            )
            if captcha_status == "timeout":
                return "captcha_timeout", "shein_home_captcha_timeout_300_seconds"
            ready_deadline = time.monotonic() + SHEIN_HOME_CAPTCHA_MANUAL_TIMEOUT_SECONDS

        remaining_seconds = max(0, int(math.ceil(ready_deadline - time.monotonic())))
        print(f"SHEIN 首页正常页面等待中：剩余 {remaining_seconds} 秒", flush=True)
        if remaining_seconds <= 0:
            return "home_not_ready", "shein_home_not_ready_after_300_seconds"
        interruptible_sleep(
            min(CAPTCHA_COUNTDOWN_PRINT_INTERVAL_SECONDS, remaining_seconds),
            label="",
            print_interval=CAPTCHA_COUNTDOWN_PRINT_INTERVAL_SECONDS,
        )

    if not is_browser_session_usable(session):
        return "browser_closed", "cloakbrowser_or_shein_page_closed_after_warmup"

    stable_seconds = random.randint(
        SHEIN_HOME_AFTER_VERIFY_STABLE_MIN_SECONDS,
        SHEIN_HOME_AFTER_VERIFY_STABLE_MAX_SECONDS,
    )
    print(f"SHEIN 首页已正常显示，进入稳定观察 {stable_seconds} 秒。", flush=True)
    interruptible_sleep(
        stable_seconds,
        label="首页验证后稳定观察",
        print_interval=VERIFY_STABLE_PRINT_INTERVAL_SECONDS,
    )
    print("SHEIN 首页稳定观察完成，准备创建商品详情页采集窗口。", flush=True)

    return "completed", "shein_home_verified_and_stable_observed"


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
    error_text_upper = (error_text or "").upper()

    if (
        final_url_lower.startswith("chrome-error://")
        or "chrome-error://chromewebdata/" in final_url_lower
        or "ERR_EMPTY_RESPONSE" in error_text_upper
        or "ERR_CONNECTION_CLOSED" in error_text_upper
    ):
        return "network_fetch_failed", "代理或网络异常，浏览器进入 chrome-error 或空响应页面"

    if contains_login_page(final_url, html_text, visible_text):
        return "login_required", "明确登录页面"

    if "/risk/challenge" in final_url_lower or "captcha_type=" in final_url_lower:
        return "blocked_or_verify", "明确验证码页面"

    body_signal_count = count_product_body_signals(html_text, visible_text) if html_text else 0
    attribute_count_debug = len(extract_description_attributes(html_text)) if html_text else 0

    if "ProductHardCapExceeded" in error_text:
        if attribute_count_debug >= FAST_MODE_MIN_ATTRIBUTE_COUNT:
            return "success", "商品属性已加载，虽达到 fast 硬截止但保留成功结果"

    if error_text:
        if contains_any(combined_text, CONNECTION_CLOSED_KEYWORDS):
            return "connection_closed", "页面或异常信息显示连接被关闭"
        if "timeout" in error_text.lower():
            if attribute_count_debug >= FAST_MODE_MIN_ATTRIBUTE_COUNT:
                return "success", "页面超时但商品主体和 Description 属性已加载，保留成功结果"
            if body_signal_count >= 4 and attribute_count_debug == 0:
                return "partial_detail_loaded", "页面主体已加载但 Description 属性为空，需要追加等待或 stable 重试"
            return "timeout", "页面请求超时"
        return "fetch_failed", error_text[:300]

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
            "detail_dwell_seconds": "0.00",
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
    row.update(infer_product_create_date_from_sku(row.get("sku")))
    return row


def apply_attributes_to_row(row: dict[str, str], attributes: dict[str, str]) -> None:
    """把全量属性写入 JSON 字段，并把已知属性映射到固定列。"""
    for original_key, field_name in ATTRIBUTE_FIELD_MAP.items():
        row[field_name] = attributes.get(original_key, "")

    row["attribute_count"] = str(len(attributes))
    row["attribute_keys"] = ",".join(attributes.keys())
    row["attributes_json"] = json.dumps(attributes, ensure_ascii=False, sort_keys=False)


def is_success_checkpoint_row(row: dict[str, str]) -> bool:
    """只有页面、解析和属性数量都成功才算可跳过的 checkpoint。"""
    return (
        normalize_text(row.get("page_status")) == "success"
        and normalize_text(row.get("parse_status")) == "success"
        and parse_int(row.get("attribute_count")) > 0
    )


def load_success_product_ids() -> set[str]:
    """从即时输出中重新读取已成功商品 ID。"""
    if not OUTPUT_CSV_PATH.exists():
        return set()
    with OUTPUT_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return {
            normalize_text(row.get("product_id"))
            for row in csv.DictReader(csv_file)
            if normalize_text(row.get("product_id")) and is_success_checkpoint_row(row)
        }


def ensure_csv_schema(path: Path, fieldnames: list[str]) -> None:
    """Upgrade an existing checkpoint header before appending new fields."""
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        existing_fieldnames = reader.fieldnames or []
        if existing_fieldnames == fieldnames:
            return
        existing_rows = list(reader)

    temp_path = path.with_suffix(f"{path.suffix}.schema_upgrade.tmp")
    try:
        with temp_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for existing_row in existing_rows:
                writer.writerow({field: existing_row.get(field, "") for field in fieldnames})
            csv_file.flush()
            os.fsync(csv_file.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def append_csv_row(path: Path, fieldnames: list[str], row: dict[str, Any]) -> None:
    """追加一行并强制刷新到磁盘。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_csv_schema(path, fieldnames)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in fieldnames})
        csv_file.flush()
        os.fsync(csv_file.fileno())


def append_result_row(row: dict[str, str]) -> None:
    append_csv_row(OUTPUT_CSV_PATH, CSV_FIELDS, row)


def append_failed_retry_row(row: dict[str, str]) -> None:
    append_csv_row(FAILED_RETRY_CSV_PATH, CSV_FIELDS, row)


def safe_append_failed_retry_row(row: dict[str, str]) -> None:
    """A locked retry CSV must never invalidate the primary checkpoint."""
    try:
        append_failed_retry_row(row)
    except PermissionError:
        print(
            "警告：failed/retry CSV 当前被占用，本条失败记录已跳过写入，"
            "但主 checkpoint 已保存，脚本继续运行。"
        )


def append_summary_row(summary_row: dict[str, Any]) -> None:
    append_csv_row(SUMMARY_CSV_PATH, D1C_SUMMARY_FIELDS, summary_row)


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

    fetch_result = fetch_detail_page(session, product_url, current_mode, product_id)
    html_text = fetch_result["html_text"]
    visible_text = fetch_result["visible_text"]
    error_text = fetch_result["error_text"]
    row["final_url"] = fetch_result["final_url"]
    row["detail_dwell_seconds"] = fetch_result.get("detail_dwell_seconds", "0.00")
    detail_captcha_detected = fetch_result.get("detail_captcha_detected") == "True"
    row["detail_captcha_detected"] = str(detail_captcha_detected)
    fetch_seconds = parse_float(fetch_result["fetch_seconds"])

    if error_text and not html_text and not detail_captcha_detected:
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

    if detail_captcha_detected:
        page_status, status_reason = "blocked_or_verify", "详情页验证码页面"
    else:
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
    if page_status in {"success", "partial_detail_loaded"}:
        row["sku"] = extract_sku(soup, html_text)
        product_create_date_fields = infer_product_create_date_from_sku(row.get("sku"))
        row.update(product_create_date_fields)
        row["title"] = extract_title(soup, html_text) or row["title"]
        row["price"] = extract_price(soup, html_text, visible_text) or row["price"]
        attributes, raw_description_text, parse_status = parse_description(html_text)
        row["parse_status"] = parse_status
        row["raw_description_text"] = raw_description_text
        apply_attributes_to_row(row, attributes)
    else:
        row["parse_status"] = "skipped_due_to_page_status"
        row["raw_description_text"] = f"页面状态为 {page_status}，跳过 Description 解析：{status_reason}"

    current_attribute_count = parse_int(row.get("attribute_count"))
    body_signal_count = count_product_body_signals(html_text, visible_text) if html_text else 0
    description_needs_recovery = (
        row.get("page_status") == "partial_detail_loaded"
        or row.get("parse_status") == "description_not_found"
        or current_attribute_count == 0
        or (len(extract_description_attributes(html_text)) if html_text else 0) == 0
    )
    recovery_excluded_statuses = {
        "blocked_or_verify",
        "login_required",
        "network_fetch_failed",
        "connection_closed",
    }
    can_recover_description = (
        description_needs_recovery
        and row.get("page_status") not in recovery_excluded_statuses
        and not detail_captcha_detected
        and body_signal_count >= 2
    )

    if can_recover_description and DESCRIPTION_EMPTY_EXTRA_WAIT_ENABLED:
        wait_for_description_attributes(session["page"], product_id)
        html_text = safe_page_html(session["page"])
        visible_text = safe_page_text(session["page"])
        soup = BeautifulSoup(html_text, "html.parser")
        final_url = safe_page_url(session["page"])
        attributes, raw_description_text, recovered_parse_status = parse_description(html_text)

        row["final_url"] = final_url or row["final_url"]
        row["raw_description_text"] = raw_description_text
        row["parse_status"] = recovered_parse_status
        if attributes:
            row["sku"] = extract_sku(soup, html_text)
            row["title"] = extract_title(soup, html_text) or row.get("title", "")
            row["price"] = (
                extract_price(soup, html_text, visible_text) or row.get("price", "")
            )
            product_create_date_fields = infer_product_create_date_from_sku(row.get("sku"))
            row.update(product_create_date_fields)
            apply_attributes_to_row(row, attributes)
            row["page_status"] = "success"
            row["parse_status"] = "success"
            row["status_reason"] = "Description 追加等待后属性加载成功"
            save_text_file(paths["html"], html_text)
            save_text_file(paths["visible_text"], visible_text)
        else:
            row["page_status"] = "partial_detail_loaded"
            row["parse_status"] = "description_not_found"
            row["attribute_count"] = "0"
            if current_mode == "stable":
                row["status_reason"] = (
                    "商品主体已加载但 Description 属性为空，等待和 stable 重试后仍失败"
                )
            else:
                row["status_reason"] = "商品主体已加载但 Description 属性为空，等待后需要 stable 重试"

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
        return random.uniform(
            BETWEEN_PRODUCT_SLEEP_MIN_SECONDS,
            BETWEEN_PRODUCT_SLEEP_MAX_SECONDS,
        )
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
    """Compatibility wrapper around the shared detail captcha wait."""
    start_time = time.monotonic()
    status, _ = wait_for_manual_captcha_clear(
        session["detail_page"],
        label="商品详情页",
        timeout_seconds=DETAIL_CAPTCHA_MANUAL_TIMEOUT_SECONDS,
    )
    elapsed_seconds = time.monotonic() - start_time
    return ("resolved" if status == "cleared" else "timeout"), elapsed_seconds


def count_key_fields(row: dict[str, str]) -> int:
    return sum(1 for field in KEY_FIELDS_FOR_STATS if row.get(field))


def should_stable_retry_due_to_empty_detail(row: dict[str, str]) -> bool:
    if row.get("page_status") in {"login_required", "blocked_or_verify"}:
        return False

    page_status = row.get("page_status")
    parse_status = row.get("parse_status")
    attribute_count = parse_int(row.get("attribute_count"))

    return (
        page_status in {"success", "partial_detail_loaded"}
        and parse_status in {"description_not_found", "parse_failed", "skipped_due_to_page_status"}
        and attribute_count == 0
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
    row["detail_dwell_seconds"] = (
        f"{sum(parse_float(item.get('detail_dwell_seconds')) for item in aggregate_rows):.2f}"
    )
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
        f"detail_dwell_seconds={row['detail_dwell_seconds']}, "
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
    print(f"详情页人工浏览停留：{row['detail_dwell_seconds']} 秒")
    print(f"下一个商品等待：{row['inter_sleep_seconds']} 秒")
    print(f"产品创建日期：{row['product_create_date']}")
    product_create_date_parse_status = row["product_create_date_parse_status"]
    if product_create_date_parse_status == "failed":
        print(
            "创建日期解析状态："
            f"failed（{row['product_create_date_parse_reason']}）"
        )
    else:
        print(f"创建日期解析状态：{product_create_date_parse_status}")
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
        f"关键字段={key_count}/{len(KEY_FIELDS_FOR_STATS)}",
        flush=True,
    )


LAST_BATCH_SLEEP_SECONDS = 0


def project_relative_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def run_one_batch(
    sold_candidates: list[dict[str, str]],
    success_product_ids: set[str],
    remaining_products: list[dict[str, str]],
    current_batch: list[dict[str, str]],
) -> str:
    """使用全新的 Playwright + KDL proxy session 采集一个小批次。"""
    global ACTIVE_SESSION, LAST_BATCH_SLEEP_SECONDS

    batch_start_time = datetime.now(timezone.utc).astimezone()
    batch_start_monotonic = time.monotonic()
    rows: list[dict[str, str]] = []
    stopped_reason = "batch_completed"
    proxy_preflight_status = "not_run"
    proxy_preflight_reason = ""
    session_type = "cloakbrowser"
    consecutive_blocked_products = 0
    consecutive_fetch_failed_products = 0
    consecutive_empty_attribute_products = 0
    stable_cooldown_remaining = 0
    current_mode = "stable"
    session: dict[str, Any] | None = None

    try:
        if not PROXY_CONFIGURED:
            stopped_reason = "proxy_not_configured"
            proxy_preflight_reason = "KDL proxy is not configured"
            print("KDL proxy 未配置，当前批次停止。")
        else:
            try:
                session = create_cloak_proxy_browser_session()
                ACTIVE_SESSION = session
                proxy_preflight_status, proxy_preflight_reason = run_proxy_preflight(session)
                print(f"proxy_preflight_status: {proxy_preflight_status}", flush=True)
                print(f"proxy_preflight_reason: {proxy_preflight_reason}", flush=True)
                if proxy_preflight_status != "success":
                    stopped_reason = "proxy_preflight_failed"
                else:
                    if BROWSERLEAKS_BEFORE_COLLECTION_ENABLED:
                        open_browserleaks_before_collection(session)

                    collection_batch = current_batch
                    if SHEIN_HOME_WARMUP_ENABLED:
                        warmup_status, warmup_reason = ensure_shein_collection_page(session)
                        print(f"shein_home_warmup_status: {warmup_status}", flush=True)
                        print(f"shein_home_warmup_reason: {warmup_reason}", flush=True)
                        if warmup_status != "completed":
                            stopped_reason = f"shein_home_warmup_{warmup_status}"
                            collection_batch = []
                        elif not is_browser_session_usable(session):
                            stopped_reason = "cloakbrowser_closed_before_detail_collection"
                            collection_batch = []
                        else:
                            detail_page = session["context"].new_page()
                            session["detail_page"] = detail_page
                            session["page"] = detail_page
                            if RESOURCE_BLOCKING_ENABLED:
                                install_resource_blocking(detail_page)
                            print("SHEIN 首页验证与预热已完成。", flush=True)
                            print("已创建独立商品详情页采集窗口。", flush=True)
                            print("正式开始当前批次商品详情页采集。", flush=True)
                    else:
                        detail_page = session["context"].new_page()
                        session["detail_page"] = detail_page
                        session["page"] = detail_page
                        if RESOURCE_BLOCKING_ENABLED:
                            install_resource_blocking(detail_page)
                    if collection_batch:
                        print(f"current batch planned: {len(collection_batch)}", flush=True)
                    for index, product in enumerate(collection_batch, start=1):
                            product_id = normalize_text(product.get("product_id")) or extract_product_id_from_url(
                                normalize_text(product.get("product_url"))
                            )
                            if product_id in load_success_product_ids():
                                print(f"checkpoint 已成功，跳过 product_id={product_id}")
                                continue

                            print(
                                f"\n采集 {index}/{len(collection_batch)}: product_id={product_id}",
                                flush=True,
                            )
                            if stable_cooldown_remaining > 0:
                                first_attempt_mode = "stable"
                                stable_cooldown_remaining -= 1
                            else:
                                first_attempt_mode = current_mode

                            first_row = fetch_and_parse_one_product(session, product, first_attempt_mode)
                            final_row = first_row
                            aggregate_rows = [first_row]
                            attempt_count = 1
                            recovery_used = False
                            final_fetch_mode = first_attempt_mode
                            captcha_wait_used = False
                            captcha_wait_seconds = 0.0
                            detail_captcha_timeout = False

                            if (
                                first_row.get("page_status") == "blocked_or_verify"
                                or first_row.get("detail_captcha_detected") == "True"
                                or is_challenge_url(first_row.get("final_url", ""))
                            ):
                                captcha_wait_used = True
                                captcha_wait_start = time.monotonic()
                                captcha_status, captcha_reason = wait_for_manual_captcha_clear(
                                    session["detail_page"],
                                    label="商品详情页",
                                    timeout_seconds=DETAIL_CAPTCHA_MANUAL_TIMEOUT_SECONDS,
                                )
                                captcha_wait_seconds = time.monotonic() - captcha_wait_start
                                if captcha_status == "cleared":
                                    print(
                                        "商品详情页验证码已通过，使用 stable 模式重新采集当前商品 "
                                        f"product_id={product_id}",
                                        flush=True,
                                    )
                                    recovery_used = True
                                    recovery_row = fetch_and_parse_one_product(session, product, "stable")
                                    aggregate_rows.append(recovery_row)
                                    final_row = recovery_row
                                    attempt_count = 2
                                    final_fetch_mode = "captcha_cleared_stable_retry"
                                else:
                                    first_row["page_status"] = "blocked_or_verify"
                                    first_row["status_reason"] = "detail_captcha_timeout_300_seconds"
                                    final_row = first_row
                                    detail_captcha_timeout = True

                            if (
                                not detail_captcha_timeout
                                and not captcha_wait_used
                                and first_attempt_mode == "fast"
                                and DESCRIPTION_EMPTY_STABLE_RETRY_ENABLED
                                and should_stable_retry_due_to_empty_detail(first_row)
                                and attempt_count < MAX_ATTEMPTS_PER_PRODUCT
                            ):
                                recovery_used = True
                                stable_cooldown_remaining = LOCAL_FAST_EMPTY_DETAIL_STABLE_COOLDOWN
                                print(
                                    f"商品 {product_id} Description 追加等待后仍为空，"
                                    "使用 stable 模式重采当前商品。",
                                    flush=True,
                                )
                                recovery_row = fetch_and_parse_one_product(session, product, "stable")
                                aggregate_rows.append(recovery_row)
                                final_row = recovery_row
                                attempt_count = 2
                                final_fetch_mode = "fast_to_stable_empty_description_retry"

                            row = apply_attempt_metadata(
                                row=final_row,
                                fetch_mode=final_fetch_mode,
                                attempt_count=attempt_count,
                                recovery_used=recovery_used,
                                manual_wait_seconds=0.0,
                                aggregate_rows=aggregate_rows,
                                captcha_wait_used=captcha_wait_used,
                                captcha_wait_seconds=captcha_wait_seconds,
                            )
                            next_mode = "stable" if stable_cooldown_remaining > 0 else "fast"
                            inter_sleep_seconds = calculate_inter_sleep_seconds(row, next_mode)
                            row["stable_success_streak"] = "0"
                            row["inter_sleep_seconds"] = f"{inter_sleep_seconds:.2f}"

                            page_status = normalize_text(row.get("page_status"))
                            final_url = normalize_text(row.get("final_url")).lower()
                            success = is_success_checkpoint_row(row)
                            empty_attributes = page_status == "success" and parse_int(row.get("attribute_count")) == 0

                            if success:
                                consecutive_blocked_products = 0
                                consecutive_fetch_failed_products = 0
                                consecutive_empty_attribute_products = 0
                                session["success_count"] += 1
                            elif page_status == "blocked_or_verify":
                                consecutive_blocked_products += 1
                                consecutive_fetch_failed_products = 0
                                consecutive_empty_attribute_products = 0
                            elif page_status == "fetch_failed":
                                consecutive_blocked_products = 0
                                consecutive_fetch_failed_products += 1
                                consecutive_empty_attribute_products = 0
                            elif empty_attributes:
                                consecutive_blocked_products = 0
                                consecutive_fetch_failed_products = 0
                                consecutive_empty_attribute_products += 1
                            else:
                                consecutive_blocked_products = 0
                                consecutive_fetch_failed_products = 0
                                consecutive_empty_attribute_products = 0

                            row["consecutive_failures"] = str(
                                max(
                                    consecutive_blocked_products,
                                    consecutive_fetch_failed_products,
                                    consecutive_empty_attribute_products,
                                )
                            )
                            append_result_row(row)
                            if not success:
                                safe_append_failed_retry_row(row)
                            rows.append(row)
                            print_product_result(row, index, len(collection_batch))

                            if detail_captcha_timeout:
                                stopped_reason = "detail_captcha_timeout_stop_current_batch"
                                break
                            if page_status == "login_required":
                                stopped_reason = "login_required_stop_current_batch"
                                break
                            if "login_force=1" in final_url:
                                stopped_reason = "login_force_stop_current_batch"
                                break
                            if consecutive_blocked_products >= MAX_CONSECUTIVE_BLOCKED_PRODUCTS:
                                stopped_reason = "max_consecutive_blocked_products_stop_current_batch"
                                break
                            if consecutive_fetch_failed_products >= MAX_CONSECUTIVE_FETCH_FAILED_PRODUCTS:
                                stopped_reason = "max_consecutive_fetch_failed_products_stop_current_batch"
                                break
                            if consecutive_empty_attribute_products >= MAX_CONSECUTIVE_EMPTY_ATTRIBUTE_PRODUCTS:
                                stopped_reason = "max_consecutive_empty_attribute_products_stop_current_batch"
                                break

                            if index < len(collection_batch):
                                print(
                                    f"等待 {inter_sleep_seconds:.2f} 秒后采集下一商品...",
                                    flush=True,
                                )
                                interruptible_sleep(
                                    inter_sleep_seconds,
                                    label="商品间等待",
                                    print_interval=5,
                                )
                            current_mode = next_mode
            finally:
                close_browser_session(session)
                if ACTIVE_SESSION is session:
                    ACTIVE_SESSION = None
                session = None
    except Exception as exc:  # noqa: BLE001 - persist a batch summary before returning.
        stopped_reason = "batch_exception"
        proxy_preflight_reason = safe_proxy_failure_reason(exc)
        if proxy_preflight_status == "not_run":
            proxy_preflight_status = "failed"
        print(f"当前批次异常停止：{proxy_preflight_reason}")
        close_browser_session(session)

    batch_end_time = datetime.now(timezone.utc).astimezone()
    remaining_after_batch = max(0, len(remaining_products) - sum(1 for row in rows if is_success_checkpoint_row(row)))
    LAST_BATCH_SLEEP_SECONDS = (
        random.randint(BATCH_SLEEP_MIN_SECONDS, BATCH_SLEEP_MAX_SECONDS)
        if UNATTENDED_LOOP_ENABLED and remaining_after_batch > 0
        else 0
    )
    append_summary_row(
        {
            "run_mode": "unattended" if UNATTENDED_LOOP_ENABLED else "single_batch",
            "input_csv_path": project_relative_path(INPUT_CSV_PATH),
            "output_csv_path": project_relative_path(OUTPUT_CSV_PATH),
            "total_candidates": len(sold_candidates),
            "already_success_count": len(success_product_ids),
            "remaining_count_before_batch": len(remaining_products),
            "batch_size": BATCH_SIZE,
            "current_batch_planned": len(current_batch),
            "current_batch_success_count": sum(1 for row in rows if is_success_checkpoint_row(row)),
            "current_batch_blocked_count": sum(
                1 for row in rows if row.get("page_status") == "blocked_or_verify"
            ),
            "current_batch_login_required_count": sum(
                1 for row in rows if row.get("page_status") == "login_required"
            ),
            "current_batch_fetch_failed_count": sum(
                1 for row in rows if row.get("page_status") == "fetch_failed"
            ),
            "current_batch_empty_attribute_count": sum(
                1
                for row in rows
                if row.get("page_status") == "success" and parse_int(row.get("attribute_count")) == 0
            ),
            "current_batch_start_time": batch_start_time.isoformat(timespec="seconds"),
            "current_batch_end_time": batch_end_time.isoformat(timespec="seconds"),
            "batch_elapsed_seconds": f"{time.monotonic() - batch_start_monotonic:.2f}",
            "sleep_seconds": LAST_BATCH_SLEEP_SECONDS,
            "stopped_reason": stopped_reason,
            "clean_url_validation_passed": "True",
            "proxy_preflight_status": proxy_preflight_status,
            "proxy_preflight_reason": proxy_preflight_reason,
            "session_type": session_type,
        }
    )
    print(f"当前批次结束：stopped_reason={stopped_reason}", flush=True)
    return stopped_reason


def run_main_loop() -> None:
    """运行 V2.9D1C Clean URL 单线程无人值守断点续采。"""
    ensure_dirs()
    print("V2.9D1C Clean URL 单线程无人值守断点续采", flush=True)
    print("输入源：data/output/v2_7b_products_10_pages_merged_clean_urls.csv", flush=True)
    print("确认：本阶段只读取 V2.7B clean URL 主表，不读取旧 V2.7 输入源", flush=True)
    print(f"browser_session_mode: {BROWSER_SESSION_MODE}", flush=True)
    print(f"cloak_browser_profile: {CLOAK_BROWSER_PROFILE_NAME}", flush=True)
    print(f"BrowserLeaks 采集前观察：{BROWSERLEAKS_BEFORE_COLLECTION_ENABLED}", flush=True)
    print(f"BrowserLeaks 观察页：{BROWSERLEAKS_URL}", flush=True)
    print(f"SHEIN 官网入口预热：{SHEIN_HOME_WARMUP_ENABLED}", flush=True)
    print(f"SHEIN 首页预热时间：{SHEIN_HOME_WARMUP_SECONDS} 秒", flush=True)
    print(
        f"首页验证码人工等待上限：{SHEIN_HOME_CAPTCHA_MANUAL_TIMEOUT_SECONDS} 秒",
        flush=True,
    )
    print(
        f"FAST 人工浏览停留："
        f"{DETAIL_PAGE_DWELL_MIN_SECONDS}-{DETAIL_PAGE_DWELL_MAX_SECONDS} 秒",
        flush=True,
    )
    print(
        f"FAST 商品间隔："
        f"{BETWEEN_PRODUCT_SLEEP_MIN_SECONDS}-{BETWEEN_PRODUCT_SLEEP_MAX_SECONDS} 秒",
        flush=True,
    )
    print(f"FAST_HUMAN_DWELL_ENABLED: {FAST_HUMAN_DWELL_ENABLED}", flush=True)
    print(f"BATCH_SIZE: {BATCH_SIZE}", flush=True)
    print(f"UNATTENDED_LOOP_ENABLED: {UNATTENDED_LOOP_ENABLED}", flush=True)
    print(f"BATCH_SLEEP_MIN_SECONDS: {BATCH_SLEEP_MIN_SECONDS}", flush=True)
    print(f"BATCH_SLEEP_MAX_SECONDS: {BATCH_SLEEP_MAX_SECONDS}", flush=True)
    print(
        f"DESCRIPTION_EMPTY_EXTRA_WAIT_ENABLED: {DESCRIPTION_EMPTY_EXTRA_WAIT_ENABLED}",
        flush=True,
    )
    print(
        f"DESCRIPTION_EMPTY_EXTRA_WAIT_MIN_SECONDS: "
        f"{DESCRIPTION_EMPTY_EXTRA_WAIT_MIN_SECONDS}",
        flush=True,
    )
    print(
        f"DESCRIPTION_EMPTY_EXTRA_WAIT_MAX_SECONDS: "
        f"{DESCRIPTION_EMPTY_EXTRA_WAIT_MAX_SECONDS}",
        flush=True,
    )
    print(
        f"DESCRIPTION_EMPTY_STABLE_RETRY_ENABLED: {DESCRIPTION_EMPTY_STABLE_RETRY_ENABLED}",
        flush=True,
    )
    print(
        f"PRODUCT_CREATE_DATE_FROM_SKU_ENABLED: {PRODUCT_CREATE_DATE_FROM_SKU_ENABLED}",
        flush=True,
    )
    print(
        "断点续采输出：data/output/v2_9d1c_detail_attributes_checkpoint_clean_urls.csv",
        flush=True,
    )

    while True:
        products = read_products()
        validate_clean_product_urls_or_raise(products)
        sold_candidates = select_sold_products(products)
        success_product_ids = load_success_product_ids()
        remaining_products = [
            product
            for product in sold_candidates
            if (
                normalize_text(product.get("product_id"))
                or extract_product_id_from_url(normalize_text(product.get("product_url")))
            )
            not in success_product_ids
        ]

        print(
            f"候选商品={len(sold_candidates)}, 已成功={len(success_product_ids)}, "
            f"待采集={len(remaining_products)}"
        )
        if not remaining_products:
            now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            append_summary_row(
                {
                    "run_mode": "unattended" if UNATTENDED_LOOP_ENABLED else "single_batch",
                    "input_csv_path": project_relative_path(INPUT_CSV_PATH),
                    "output_csv_path": project_relative_path(OUTPUT_CSV_PATH),
                    "total_candidates": len(sold_candidates),
                    "already_success_count": len(success_product_ids),
                    "remaining_count_before_batch": 0,
                    "batch_size": BATCH_SIZE,
                    "current_batch_planned": 0,
                    "current_batch_start_time": now,
                    "current_batch_end_time": now,
                    "batch_elapsed_seconds": "0.00",
                    "sleep_seconds": 0,
                    "stopped_reason": "all_completed",
                    "clean_url_validation_passed": "True",
                    "proxy_preflight_status": "not_run",
                    "session_type": "cloakbrowser",
                }
            )
            print("V2.9D1C 全部完成")
            return

        current_batch = remaining_products[:BATCH_SIZE]
        run_one_batch(
            sold_candidates,
            success_product_ids,
            remaining_products,
            current_batch,
        )

        if not UNATTENDED_LOOP_ENABLED:
            print("UNATTENDED_LOOP_ENABLED=False，完成一批后退出。")
            return

        refreshed_success_ids = load_success_product_ids()
        still_remaining = [
            product
            for product in sold_candidates
            if (
                normalize_text(product.get("product_id"))
                or extract_product_id_from_url(normalize_text(product.get("product_url")))
            )
            not in refreshed_success_ids
        ]
        if still_remaining:
            print(f"批次间休眠 {LAST_BATCH_SLEEP_SECONDS} 秒...")
            interruptible_sleep(
                LAST_BATCH_SLEEP_SECONDS,
                label="批次间休眠",
                print_interval=5,
            )


def main() -> None:
    """Run the collector with unified Ctrl+C cleanup."""
    global ACTIVE_SESSION, STOP_REQUESTED

    session: dict[str, Any] | None = None
    STOP_REQUESTED = False
    print("手动停止方式：请先点击 VS Code 终端，再按 Ctrl+C。", flush=True)
    print(
        "收到 Ctrl+C 后，脚本会关闭 BrowserLeaks / SHEIN / 商品详情页并安全退出。",
        flush=True,
    )
    try:
        run_main_loop()
    except KeyboardInterrupt:
        STOP_REQUESTED = True
        print("收到 Ctrl+C 手动停止信号，正在关闭浏览器并安全退出...", flush=True)
    finally:
        close_browser_session(session)
        close_browser_session(ACTIVE_SESSION)
        ACTIVE_SESSION = None
        print("V2.9D1C 已安全退出。", flush=True)


if __name__ == "__main__":
    main()
