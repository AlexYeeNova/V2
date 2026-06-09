"""V2.9D-1B CloakBrowser + KDL proxy BrowserLeaks IP diagnostic."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from cloakbrowser import launch as cloak_launch
except ImportError:
    cloak_launch = None

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRETS_ENV_PATH = PROJECT_ROOT / "secrets" / "kdl_proxy.env"

OUTPUT_DIR = PROJECT_ROOT / "data" / "debug" / "v2_9d1b_cloak_browserleaks_ip_check"
OUTPUT_HTML_PATH = OUTPUT_DIR / "browserleaks_ip.html"
OUTPUT_TEXT_PATH = OUTPUT_DIR / "browserleaks_ip_visible_text.txt"
OUTPUT_SCREENSHOT_PATH = OUTPUT_DIR / "browserleaks_ip.png"
OUTPUT_JSON_PATH = OUTPUT_DIR / "browserleaks_ip_summary.json"

TARGET_URL = "https://browserleaks.com/ip"
CLOAK_HEADLESS = False
CLOAK_HUMANIZE_ENABLED = True
CLOAK_GEOIP_ENABLED = False
CLOAK_PROXY_MODE = "url"
PAGE_TIMEOUT_MS = 60000
POST_LOAD_WAIT_SECONDS = 8
BROWSER_KEEP_OPEN_SECONDS = 300


def load_proxy_config() -> tuple[str, str, str]:
    if SECRETS_ENV_PATH.exists():
        if load_dotenv is None:
            raise RuntimeError("未安装 python-dotenv，请先执行：pip install python-dotenv")
        load_dotenv(SECRETS_ENV_PATH, override=False)

    return (
        os.getenv("KDL_PROXY_SERVER", ""),
        os.getenv("KDL_PROXY_USERNAME", ""),
        os.getenv("KDL_PROXY_PASSWORD", ""),
    )


def build_proxy_url(server: str, username: str, password: str) -> str:
    safe_server = server
    if safe_server.startswith("http://"):
        safe_server = safe_server.replace("http://", "", 1)
    elif safe_server.startswith("https://"):
        safe_server = safe_server.replace("https://", "", 1)
    return f"http://{username}:{password}@{safe_server}"


def close_browser_resources(browser: Any, context: Any, page: Any) -> None:
    for resource in (page, context, browser):
        if resource is None:
            continue
        try:
            resource.close()
        except Exception:
            pass


def main() -> None:
    proxy_server, proxy_username, proxy_password = load_proxy_config()
    proxy_server_configured = bool(proxy_server)
    proxy_auth_configured = bool(proxy_username and proxy_password)

    print("V2.9D-1B CloakBrowser BrowserLeaks IP Check 可视化模式启动")
    print(f"TARGET_URL: {TARGET_URL}")
    print(f"CLOAK_HEADLESS: {CLOAK_HEADLESS}")
    print(f"BROWSER_KEEP_OPEN_SECONDS: {BROWSER_KEEP_OPEN_SECONDS}")
    print(f"CLOAK_HUMANIZE_ENABLED: {CLOAK_HUMANIZE_ENABLED}")
    print(f"CLOAK_PROXY_MODE: {CLOAK_PROXY_MODE}")
    print(f"KDL_PROXY_SERVER configured: {proxy_server_configured}")
    print(f"KDL_PROXY_AUTH configured: {proxy_auth_configured}")

    if cloak_launch is None:
        raise RuntimeError("未安装 cloakbrowser，请先执行：pip install cloakbrowser")
    if not proxy_server_configured or not proxy_auth_configured:
        raise RuntimeError("KDL proxy is not fully configured in secrets/kdl_proxy.env")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    proxy_url = build_proxy_url(proxy_server, proxy_username, proxy_password)

    browser = None
    context = None
    page = None
    try:
        try:
            browser = cloak_launch(
                headless=CLOAK_HEADLESS,
                proxy=proxy_url,
                humanize=CLOAK_HUMANIZE_ENABLED,
            )
        except Exception as exc:
            print(f"CloakBrowser 启动失败：{type(exc).__name__}: {exc}")
            raise

        context = browser.new_context(
            locale="en-SG",
            timezone_id="Asia/Singapore",
            viewport={"width": 1366, "height": 768},
            screen={"width": 1366, "height": 768},
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
        )
        page = context.new_page()

        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                print("BrowserLeaks networkidle 等待超时，将继续保存当前页面结果。")

            time.sleep(POST_LOAD_WAIT_SECONDS)
            final_url = page.url
            title = page.title()
            visible_text = page.locator("body").inner_text(timeout=10000)
            html_text = page.content()
            page.screenshot(path=str(OUTPUT_SCREENSHOT_PATH), full_page=True)

            OUTPUT_HTML_PATH.write_text(html_text, encoding="utf-8")
            OUTPUT_TEXT_PATH.write_text(visible_text, encoding="utf-8")

            summary = {
                "target_url": TARGET_URL,
                "final_url": final_url,
                "title": title,
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "cloak_headless": CLOAK_HEADLESS,
                "cloak_humanize_enabled": CLOAK_HUMANIZE_ENABLED,
                "cloak_geoip_enabled": CLOAK_GEOIP_ENABLED,
                "cloak_proxy_mode": CLOAK_PROXY_MODE,
                "kdl_proxy_configured": proxy_server_configured,
                "kdl_proxy_auth_configured": proxy_auth_configured,
                "visible_text_saved_path": str(OUTPUT_TEXT_PATH),
                "html_saved_path": str(OUTPUT_HTML_PATH),
                "screenshot_saved_path": str(OUTPUT_SCREENSHOT_PATH),
            }
            OUTPUT_JSON_PATH.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"BrowserLeaks 页面访问失败：{type(exc).__name__}: {exc}")
            raise

        print("BrowserLeaks 页面已在可视化浏览器中打开。")
        print("请查看浏览器窗口中的 IP Address、WebRTC、DNS、IPv6、Timezone 等信息。")
        print("同时已保存 HTML、截图、可见文本和 JSON 摘要到 debug 目录。")
        print(f"final_url: {final_url}")
        print(f"title: {title}")
        print(f"HTML 保存路径：{OUTPUT_HTML_PATH}")
        print(f"可见文本保存路径：{OUTPUT_TEXT_PATH}")
        print(f"截图保存路径：{OUTPUT_SCREENSHOT_PATH}")
        print(f"JSON 摘要保存路径：{OUTPUT_JSON_PATH}")
        print(f"浏览器将保持打开 {BROWSER_KEEP_OPEN_SECONDS} 秒，方便人工查看 BrowserLeaks 结果。")
        print("你可以直接在打开的浏览器窗口里查看 IP、WebRTC、DNS、IPv6 等检测结果。")
        time.sleep(BROWSER_KEEP_OPEN_SECONDS)
    finally:
        close_browser_resources(browser, context, page)


if __name__ == "__main__":
    main()
