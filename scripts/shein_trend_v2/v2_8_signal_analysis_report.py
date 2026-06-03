"""V2.8：分类页信号交叉分析报告。

本脚本只基于 V2.7 分类页合并数据做本地统计，不访问网络、不重新采集、
不计算 trend_score，也不输出 HOT/WARM/NORMAL。
"""

from __future__ import annotations

import csv
import html
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# 项目根目录、输入文件与输出报告路径。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_7_products_10_pages_merged.csv"
REPORT_OUTPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_8_signal_analysis_report.txt"
HTML_REPORT_OUTPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_8_signal_analysis_report.html"


STYLE_KEYWORDS = [
    "casual",
    "elegant",
    "minimalist",
    "sexy",
    "retro",
    "vintage",
    "y2k",
    "boho",
    "chic",
    "streetwear",
    "korean",
    "cute",
    "business",
]

SCENARIO_KEYWORDS = [
    "vacation",
    "holiday",
    "party",
    "beach",
    "school",
    "commute",
    "wedding",
    "work",
    "sports",
    "festival",
    "date",
    "graduation",
    "birthday",
    "office",
    "street",
]

DESIGN_ELEMENT_PHRASES = [
    # 领型
    "crew neck",
    "round neck",
    "v neck",
    "v-neck",
    "square neck",
    "scoop neck",
    "halter neck",
    "mock neck",
    "notch neck",
    "polo collar",
    "lapel collar",
    "sweetheart neck",
    # 肩部与袖型
    "off shoulder",
    "off-shoulder",
    "one shoulder",
    "cold shoulder",
    "drop shoulder",
    "cap sleeve",
    "puff sleeve",
    "batwing sleeve",
    "lantern sleeve",
    "bell sleeve",
    # 腰部
    "high waist",
    "low waist",
    "elastic waist",
    "drawstring waist",
    "paperbag waist",
    # 门襟与闭合
    "button front",
    "zip front",
    "zipper front",
    "tie front",
    "knot front",
    # 工艺细节
    "lace up",
    "lace-up",
    "cut out",
    "cut-out",
    "backless",
    "ruched",
    "pleated",
    "ruffle hem",
    "split hem",
    "asymmetrical hem",
    "contrast trim",
    "lace trim",
    "mesh panel",
    "ribbed knit",
    # 图案与印花
    "polka dot",
    "floral print",
    "flower print",
    "letter print",
    "graphic print",
    "striped print",
    "animal print",
    "leopard print",
    "color block",
    "colour block",
    # 可从标题中较稳定识别的廓形/裤型
    "wide leg",
    "straight leg",
    "flare leg",
    "skinny fit",
    "slim fit",
    "bodycon dress",
    "a line",
    "a-line",
    "wrap dress",
    "slip dress",
    "camisole top",
    "crop top",
    "spaghetti strap",
]

PHRASE_ALIASES = {
    "v-neck": "v neck",
    "off-shoulder": "off shoulder",
    "a-line": "a line",
    "lace-up": "lace up",
    "cut-out": "cut out",
    "colour block": "color block",
    "zipper front": "zip front",
    "flower print": "floral print",
}

PRICE_BANDS = [
    ("0-5", 0, 5),
    ("5-10", 5, 10),
    ("10-15", 10, 15),
    ("15-20", 15, 20),
    ("20+", 20, None),
]


@dataclass
class SignalCount:
    """记录某个维度下三类信号商品数量。"""

    high_exposure_count: int = 0
    sales_signal_count: int = 0
    strong_signal_count: int = 0


@dataclass
class SalesTagStats:
    """记录 sales_tag 清洗统计。"""

    non_empty_count: int
    real_sales_count: int
    excluded_count: int
    excluded_examples: list[tuple[str, int]]


@dataclass
class AnalysisResult:
    """保存一次分析得到的全部统计结果，供 TXT 和 HTML 共同使用。"""

    total_count: int
    high_exposure_count: int
    sales_signal_count: int
    strong_signal_count: int
    sales_tag_stats: SalesTagStats
    price_signal_rows: list[tuple[str, SignalCount]]
    style_signal_rows: list[tuple[str, SignalCount]]
    scenario_signal_rows: list[tuple[str, SignalCount]]
    design_element_rows: list[tuple[str, SignalCount]]


def read_products(csv_path: Path) -> list[dict[str, str]]:
    """读取 V2.7 本地合并数据，不访问网络。"""
    if not csv_path.exists():
        raise FileNotFoundError(f"输入 CSV 文件不存在：{csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        return list(csv.DictReader(csv_file))


def parse_int(value: str) -> int:
    """安全解析整数字段。"""
    try:
        return int(float((value or "").strip()))
    except ValueError:
        return 0


def parse_price(price_text: str) -> float | None:
    """从 price 字段中提取数字价格。"""
    match = re.search(r"\d+(?:[.,]\d{1,2})?", price_text or "")
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def get_price_band(price: float) -> str:
    """根据价格数字匹配价格带。"""
    for band_name, lower_bound, upper_bound in PRICE_BANDS:
        if price >= lower_bound and (upper_bound is None or price < upper_bound):
            return band_name
    return ""


def normalize_sales_tag(sales_tag: Any) -> str:
    """标准化 sales_tag 文本，兼容 None、NaN 与空值。"""
    if sales_tag is None:
        return ""
    if isinstance(sales_tag, float) and math.isnan(sales_tag):
        return ""
    return str(sales_tag).strip()


def is_real_sales_tag(sales_tag: Any) -> bool:
    """只有 sales_tag 中包含 sold，才视为真实销量标签。"""
    return "sold" in normalize_sales_tag(sales_tag).lower()


def is_high_exposure(product: dict[str, str]) -> bool:
    """appear_count >= 2 即认为高曝光。"""
    return parse_int(product.get("appear_count", "")) >= 2


def has_strong_signal(product: dict[str, str]) -> bool:
    """同时高曝光且具备 sold 销量标签，才认为强信号。"""
    return is_high_exposure(product) and is_real_sales_tag(product.get("sales_tag"))


def tokenize_title(title: str) -> list[str]:
    """按 [a-zA-Z0-9]+ 拆词，并统一转为小写，保留 y2k 这类数字关键词。"""
    return [word.lower() for word in re.findall(r"[a-zA-Z0-9]+", title or "")]


def normalize_title_for_phrase_match(title: str) -> str:
    """标准化短语匹配文本：小写、连字符转空格、去除多余空格。"""
    lowered_title = (title or "").lower().replace("-", " ")
    return re.sub(r"\s+", " ", lowered_title).strip()


def normalize_design_phrase(phrase: str) -> str:
    """标准化设计元素短语，并应用别名归一。"""
    normalized_phrase = normalize_title_for_phrase_match(phrase)
    return PHRASE_ALIASES.get(phrase.lower(), normalized_phrase)


def calc_ratio(count: int, total_count: int) -> str:
    """格式化占比。"""
    if total_count <= 0:
        return "0.00%"
    return f"{count / total_count:.2%}"


def add_product_signal(signal_count: SignalCount, product: dict[str, str]) -> None:
    """把单个商品的三类信号累加到指定统计项。"""
    if is_high_exposure(product):
        signal_count.high_exposure_count += 1
    if is_real_sales_tag(product.get("sales_tag")):
        signal_count.sales_signal_count += 1
    if has_strong_signal(product):
        signal_count.strong_signal_count += 1


def sort_signal_items(signal_map: dict[str, SignalCount]) -> list[tuple[str, SignalCount]]:
    """按强信号、真实销量标签、高曝光数量排序。"""
    return sorted(
        signal_map.items(),
        key=lambda item: (
            item[1].strong_signal_count,
            item[1].sales_signal_count,
            item[1].high_exposure_count,
        ),
        reverse=True,
    )


def analyze_price_bands(products: list[dict[str, str]]) -> dict[str, SignalCount]:
    """按价格带统计三类信号数量。"""
    price_signal_map = {band_name: SignalCount() for band_name, _, _ in PRICE_BANDS}
    for product in products:
        price = parse_price(product.get("price", ""))
        if price is None:
            continue
        price_band = get_price_band(price)
        if price_band:
            add_product_signal(price_signal_map[price_band], product)
    return price_signal_map


def analyze_keyword_group(products: list[dict[str, str]], keywords: list[str]) -> dict[str, SignalCount]:
    """统计风格或场景词库中各关键词的三类信号数量。"""
    keyword_signal_map = {keyword: SignalCount() for keyword in keywords}
    keyword_set = set(keywords)
    for product in products:
        title_words = set(tokenize_title(product.get("title", "")))
        for keyword in sorted(title_words & keyword_set):
            add_product_signal(keyword_signal_map[keyword], product)
    return keyword_signal_map


def analyze_design_elements(products: list[dict[str, str]]) -> dict[str, SignalCount]:
    """基于服装设计短语词库统计设计元素与细节。"""
    standard_phrases = sorted({normalize_design_phrase(phrase) for phrase in DESIGN_ELEMENT_PHRASES})
    design_signal_map = {phrase: SignalCount() for phrase in standard_phrases}

    for product in products:
        normalized_title = normalize_title_for_phrase_match(product.get("title", ""))
        matched_phrases: set[str] = set()
        for phrase in standard_phrases:
            pattern = r"\b" + re.escape(phrase) + r"\b"
            if re.search(pattern, normalized_title):
                matched_phrases.add(phrase)

        for phrase in matched_phrases:
            add_product_signal(design_signal_map[phrase], product)

    return design_signal_map


def analyze_sales_tag_stats(products: list[dict[str, str]]) -> SalesTagStats:
    """统计 sales_tag 清洗结果和被排除的非销量标签示例。"""
    non_empty_tags = [normalize_sales_tag(product.get("sales_tag")) for product in products]
    non_empty_tags = [tag for tag in non_empty_tags if tag]
    real_sales_tags = [tag for tag in non_empty_tags if is_real_sales_tag(tag)]
    excluded_tags = [tag for tag in non_empty_tags if not is_real_sales_tag(tag)]
    return SalesTagStats(
        non_empty_count=len(non_empty_tags),
        real_sales_count=len(real_sales_tags),
        excluded_count=len(excluded_tags),
        excluded_examples=Counter(excluded_tags).most_common(10),
    )


def format_signal_table(title: str, first_column_name: str, rows: list[tuple[str, SignalCount]]) -> list[str]:
    """格式化三类信号统计表。"""
    lines = [
        title,
        "",
        f"{first_column_name:<16}高曝光商品        真实销量标签商品        强信号商品",
        "",
    ]
    for name, signal_count in rows:
        row_text = (
            f"{name:<18}"
            + f"{signal_count.high_exposure_count}个".ljust(18)
            + f"{signal_count.sales_signal_count}个".ljust(22)
            + f"{signal_count.strong_signal_count}个"
        )
        lines.append(row_text)
    return lines


def analyze_products(products: list[dict[str, str]]) -> AnalysisResult:
    """执行一次完整统计，避免 TXT 和 HTML 报告重复计算后不一致。"""
    total_count = len(products)
    high_exposure_count = sum(1 for product in products if is_high_exposure(product))
    sales_signal_count = sum(1 for product in products if is_real_sales_tag(product.get("sales_tag")))
    strong_signal_count = sum(1 for product in products if has_strong_signal(product))
    sales_tag_stats = analyze_sales_tag_stats(products)
    price_signal_map = analyze_price_bands(products)
    style_signal_rows = sort_signal_items(analyze_keyword_group(products, STYLE_KEYWORDS))[:10]
    scenario_signal_rows = sort_signal_items(analyze_keyword_group(products, SCENARIO_KEYWORDS))[:10]
    design_element_rows = [
        item
        for item in sort_signal_items(analyze_design_elements(products))
        if item[1].high_exposure_count > 0
        or item[1].sales_signal_count > 0
        or item[1].strong_signal_count > 0
    ][:10]

    return AnalysisResult(
        total_count=total_count,
        high_exposure_count=high_exposure_count,
        sales_signal_count=sales_signal_count,
        strong_signal_count=strong_signal_count,
        sales_tag_stats=sales_tag_stats,
        price_signal_rows=[(band_name, price_signal_map[band_name]) for band_name, _, _ in PRICE_BANDS],
        style_signal_rows=style_signal_rows,
        scenario_signal_rows=scenario_signal_rows,
        design_element_rows=design_element_rows,
    )


def build_report(result: AnalysisResult) -> str:
    """生成 V2.8 分类页信号交叉分析 TXT 报告。"""
    report_lines = [
        "V2.8版本，分类页信号交叉分析结果：",
        "",
        f"1. 总商品数：{result.total_count}",
        f"2. 高曝光商品数：{result.high_exposure_count}（{calc_ratio(result.high_exposure_count, result.total_count)}）",
        f"3. 真实销量标签商品数：{result.sales_signal_count}（{calc_ratio(result.sales_signal_count, result.total_count)}）",
        f"4. 强信号商品数：{result.strong_signal_count}（{calc_ratio(result.strong_signal_count, result.total_count)}）",
        "",
        "-" * 50,
        "",
    ]
    report_lines.extend(format_signal_table("【价格带分析】", "价格带", result.price_signal_rows))
    report_lines.extend(["", "-" * 50, ""])
    report_lines.extend(format_signal_table("【风格分析（Top10）】", "风格", result.style_signal_rows))
    report_lines.extend(["", "-" * 50, ""])
    report_lines.extend(format_signal_table("【场景分析（Top10）】", "场景", result.scenario_signal_rows))
    report_lines.extend(["", "-" * 50, ""])
    report_lines.extend(
        format_signal_table(
            "【设计元素与细节分析】(服装设计短语 Top 10)",
            "设计元素",
            result.design_element_rows,
        )
    )
    report_lines.extend(
        [
            "",
            "-" * 50,
            "",
            "说明：本报告只基于实际平台采集的真实数据分析，所有数据均可在采集的报表中溯源。",
            "",
            "真实销量标签商品：仅统计 sales_tag 中包含 sold 的商品；SAVE、NEW、折扣、优惠等标签不计入销量信号。",
            "",
            "强信号商品：同时具备高曝光率和真实销量标签的商品（同时满足平台曝光和已出现 sold 销量信号）。",
        ]
    )
    return "\n".join(report_lines)


def html_escape(value: object) -> str:
    """转义 HTML 文本，避免特殊字符破坏页面。"""
    return html.escape(str(value), quote=True)


def build_html_table(
    title: str,
    first_column_name: str,
    rows: list[tuple[str, SignalCount]],
    subtitle: str = "",
) -> str:
    """生成 HTML 三类信号表格。"""
    body_rows = []
    for name, signal_count in rows:
        body_rows.append(
            "<tr>"
            f"<td>{html_escape(name)}</td>"
            f"<td class=\"num\">{signal_count.high_exposure_count}</td>"
            f"<td class=\"num\">{signal_count.sales_signal_count}</td>"
            f"<td class=\"num\">{signal_count.strong_signal_count}</td>"
            "</tr>"
        )
    return (
        "<section class=\"card\">"
        f"<h2>{html_escape(title)}</h2>"
        f"{f'<p class=\"subtitle\">{html_escape(subtitle)}</p>' if subtitle else ''}"
        "<table>"
        "<thead><tr>"
        f"<th>{html_escape(first_column_name)}</th>"
        "<th>高曝光商品</th>"
        "<th>真实销量标签商品</th>"
        "<th>强信号商品</th>"
        "</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        "</section>"
    )


def build_metric_card(title: str, value: int, total_count: int | None = None) -> str:
    """生成核心指标卡片。"""
    ratio_text = "" if total_count is None else f"<span>{calc_ratio(value, total_count)}</span>"
    return (
        "<div class=\"metric-card\">"
        f"<div class=\"metric-title\">{html_escape(title)}</div>"
        f"<div class=\"metric-value\">{value}</div>"
        f"{ratio_text}"
        "</div>"
    )


def build_html_report(result: AnalysisResult) -> str:
    """生成单文件 HTML 报告。"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>V2.8 分类页信号交叉分析报告</title>
  <style>
    body {{
      margin: 0;
      background: #ffffff;
      color: #222;
      font-family: "Microsoft YaHei", Arial, sans-serif;
      line-height: 1.6;
    }}
    .page {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }}
    h1 {{
      margin: 0 0 20px;
      font-size: 28px;
      font-weight: 700;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 20px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }}
    .metric-card,
    .card {{
      border: 1px solid #ddd;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }}
    .metric-card {{
      padding: 16px;
    }}
    .metric-title {{
      color: #666;
      font-size: 14px;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-size: 28px;
      font-weight: 700;
      text-align: right;
    }}
    .metric-card span {{
      display: block;
      text-align: right;
      color: #777;
      font-size: 13px;
    }}
    .card {{
      padding: 18px;
      margin-top: 18px;
    }}
    .subtitle {{
      margin: -6px 0 12px;
      color: #666;
      font-size: 14px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      border: 1px solid #d8d8d8;
      padding: 10px 12px;
      vertical-align: middle;
      word-break: break-word;
    }}
    th {{
      background: #f2f3f5;
      text-align: left;
      font-weight: 700;
    }}
    .num {{
      text-align: right;
      font-variant-numeric: tabular-nums;
    }}
    .note {{
      color: #444;
      background: #fafafa;
    }}
    @media (max-width: 800px) {{
      .metrics {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <h1>V2.8 分类页信号交叉分析报告</h1>
    <section class="metrics">
      {build_metric_card("总商品数", result.total_count)}
      {build_metric_card("高曝光商品数", result.high_exposure_count, result.total_count)}
      {build_metric_card("真实销量标签商品数", result.sales_signal_count, result.total_count)}
      {build_metric_card("强信号商品数", result.strong_signal_count, result.total_count)}
    </section>
    {build_html_table("价格带分析", "价格带", result.price_signal_rows)}
    {build_html_table("风格分析 Top10", "风格", result.style_signal_rows)}
    {build_html_table("场景分析 Top10", "场景", result.scenario_signal_rows)}
    {build_html_table("设计元素与细节分析", "设计元素", result.design_element_rows, "基于服装设计短语词库匹配的 Top10")}
    <section class="card note">
      <h2>数据边界说明</h2>
      <p>说明：本报告只基于实际平台采集的真实数据分析，所有数据均可在采集的报表中溯源。</p>
      <p>真实销量标签商品：仅统计 sales_tag 中包含 sold 的商品；SAVE、NEW、折扣、优惠等标签不计入销量信号。</p>
      <p>强信号商品：同时具备高曝光率和真实销量标签的商品（同时满足平台曝光和已出现 sold 销量信号）。</p>
    </section>
  </main>
</body>
</html>
"""


def save_report(report_text: str, output_file: Path) -> None:
    """保存 UTF-8 文本报告。"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report_text, encoding="utf-8")


def save_html_report(result: AnalysisResult, output_file: Path) -> None:
    """保存单文件 HTML 报告。"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(build_html_report(result), encoding="utf-8")


def print_sales_tag_cleaning_stats(result: AnalysisResult) -> None:
    """打印销量标签清洗统计，方便确认 SAVE/NEW/折扣未计入销量信号。"""
    stats = result.sales_tag_stats
    print("销量标签清洗统计：")
    print(f"总商品数：{result.total_count}")
    print(f"sales_tag 非空商品数：{stats.non_empty_count}")
    print(f"sales_tag 包含 sold 商品数：{stats.real_sales_count}")
    print(f"被排除的非销量标签数量：{stats.excluded_count}")
    print("非销量标签示例 Top10：")
    if not stats.excluded_examples:
        print("- 无")
    for tag, count in stats.excluded_examples:
        print(f"- {tag}：{count}")


def main() -> None:
    """执行 V2.8 分类页信号交叉分析。"""
    products = read_products(INPUT_FILE)
    result = analyze_products(products)
    report_text = build_report(result)
    save_report(report_text, REPORT_OUTPUT_FILE)
    save_html_report(result, HTML_REPORT_OUTPUT_FILE)

    print(f"总商品数：{result.total_count}")
    print(f"高曝光商品数：{result.high_exposure_count}")
    print(f"真实销量标签商品数：{result.sales_signal_count}")
    print(f"强信号商品数：{result.strong_signal_count}")
    print_sales_tag_cleaning_stats(result)
    print(f"报告保存路径：{REPORT_OUTPUT_FILE}")
    print(f"HTML报告保存路径：{HTML_REPORT_OUTPUT_FILE}")


if __name__ == "__main__":
    main()
