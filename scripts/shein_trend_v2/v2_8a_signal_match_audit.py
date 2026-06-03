"""V2.8A：分类页信号匹配明细校验工具。

本工具用于核查 V2.8 报告中“场景分析”和“设计元素与细节分析”
到底匹配了哪些商品。脚本只读取本地 V2.7 合并数据，不访问网络。
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# 项目路径配置。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_7_products_10_pages_merged.csv"
AUDIT_OUTPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_8a_signal_match_audit.csv"
SUMMARY_OUTPUT_FILE = PROJECT_ROOT / "data" / "output" / "v2_8a_signal_match_summary.csv"


# 与 V2.8 报告一致的风格词库。当前 V2.8A 重点不输出风格明细，但保留词库方便核对口径。
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


# 与 V2.8 报告一致的场景词库。
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


# 与 V2.8 报告一致的设计元素短语词库。
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


# 与 V2.8 报告一致的短语别名归一规则。
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


# V2.8 当前的场景分析和设计元素分析不使用 STOP_WORDS。
# 这里保留常量，是为了明确“与 V2.8 口径一致：不额外过滤场景/设计短语”。
STOP_WORDS: set[str] = set()


AUDIT_FIELDS = [
    "analysis_type",
    "keyword",
    "product_id",
    "title",
    "price",
    "sales_tag",
    "is_real_sales",
    "appear_count",
    "is_high_exposure",
    "is_strong_signal",
    "match_rule",
    "matched_text",
]

SUMMARY_FIELDS = [
    "analysis_type",
    "keyword",
    "total_match_count",
    "high_exposure_count",
    "real_sales_count",
    "strong_signal_count",
]


@dataclass
class MatchRecord:
    """记录单个商品对单个关键词的命中结果。"""

    analysis_type: str
    keyword: str
    product: dict[str, str]
    match_rule: str
    matched_text: str


def read_products(csv_path: Path) -> list[dict[str, str]]:
    """读取 V2.7 合并数据。"""
    if not csv_path.exists():
        raise FileNotFoundError(f"输入文件不存在：{csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def normalize_text(value: Any) -> str:
    """安全转为字符串并去除首尾空白，兼容 None 和 NaN。"""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def parse_int(value: Any) -> int:
    """安全解析整数。"""
    try:
        return int(float(normalize_text(value)))
    except ValueError:
        return 0


def is_real_sales_tag(sales_tag: Any) -> bool:
    """只有 sales_tag 小写后包含 sold，才算真实销量标签。"""
    return "sold" in normalize_text(sales_tag).lower()


def is_high_exposure(product: dict[str, str]) -> bool:
    """appear_count >= 2 即为高曝光商品。"""
    return parse_int(product.get("appear_count")) >= 2


def is_strong_signal(product: dict[str, str]) -> bool:
    """同时高曝光且带 sold 销量标签，即为强信号商品。"""
    return is_high_exposure(product) and is_real_sales_tag(product.get("sales_tag"))


def tokenize_title(title: str) -> list[str]:
    """按 [a-zA-Z0-9]+ 拆词，场景词用完整 token 匹配。"""
    return [word.lower() for word in re.findall(r"[a-zA-Z0-9]+", title or "")]


def normalize_title_for_phrase_match(title: str) -> str:
    """短语匹配前的标题归一：小写、连字符转空格、压缩多余空格。"""
    lowered_title = (title or "").lower().replace("-", " ")
    return re.sub(r"\s+", " ", lowered_title).strip()


def normalize_design_phrase(phrase: str) -> str:
    """设计短语归一，并应用 V2.8 同款 alias。"""
    normalized_phrase = normalize_title_for_phrase_match(phrase)
    return PHRASE_ALIASES.get(phrase.lower(), normalized_phrase)


def build_phrase_variant_pattern(standard_phrase: str) -> re.Pattern[str]:
    """生成可匹配空格或连字符变体的短语正则。"""
    tokens = standard_phrase.split()
    joined_tokens = r"(?:\s+|-)+".join(re.escape(token) for token in tokens)
    return re.compile(r"\b" + joined_tokens + r"\b", re.IGNORECASE)


def find_design_matched_text(title: str, standard_phrase: str) -> str:
    """返回标题中实际命中的设计短语文本，用于人工核查。"""
    pattern = build_phrase_variant_pattern(standard_phrase)
    match = pattern.search(title or "")
    if match:
        return match.group(0)
    return standard_phrase


def match_scenario_keywords(product: dict[str, str]) -> list[MatchRecord]:
    """按完整词匹配场景词，street 不会匹配 streetwear。"""
    title_words = set(tokenize_title(product.get("title", "")))
    records: list[MatchRecord] = []
    for keyword in SCENARIO_KEYWORDS:
        if keyword in title_words:
            records.append(
                MatchRecord(
                    analysis_type="scenario",
                    keyword=keyword,
                    product=product,
                    match_rule="完整词匹配：[a-zA-Z0-9]+ token 等于关键词",
                    matched_text=keyword,
                )
            )
    return records


def match_design_elements(product: dict[str, str], standard_phrases: list[str]) -> list[MatchRecord]:
    """按设计短语匹配标题，支持空格和连字符变体。"""
    title = product.get("title", "")
    normalized_title = normalize_title_for_phrase_match(title)
    records: list[MatchRecord] = []

    for phrase in standard_phrases:
        pattern = r"\b" + re.escape(phrase) + r"\b"
        if re.search(pattern, normalized_title):
            records.append(
                MatchRecord(
                    analysis_type="design_element",
                    keyword=phrase,
                    product=product,
                    match_rule="短语边界匹配：标题连字符归一为空格，支持空格/连字符变体",
                    matched_text=find_design_matched_text(title, phrase),
                )
            )
    return records


def build_audit_row(record: MatchRecord) -> dict[str, str]:
    """把命中记录转换为 CSV 行。"""
    product = record.product
    real_sales = is_real_sales_tag(product.get("sales_tag"))
    high_exposure = is_high_exposure(product)
    strong_signal = is_strong_signal(product)
    return {
        "analysis_type": record.analysis_type,
        "keyword": record.keyword,
        "product_id": normalize_text(product.get("product_id")),
        "title": normalize_text(product.get("title")),
        "price": normalize_text(product.get("price")),
        "sales_tag": normalize_text(product.get("sales_tag")),
        "is_real_sales": str(real_sales).upper(),
        "appear_count": normalize_text(product.get("appear_count")),
        "is_high_exposure": str(high_exposure).upper(),
        "is_strong_signal": str(strong_signal).upper(),
        "match_rule": record.match_rule,
        "matched_text": record.matched_text,
    }


def build_summary_rows(audit_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """根据明细行生成关键词汇总。"""
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in audit_rows:
        groups.setdefault((row["analysis_type"], row["keyword"]), []).append(row)

    summary_rows: list[dict[str, str]] = []
    for analysis_type, keywords in [
        ("scenario", SCENARIO_KEYWORDS),
        ("design_element", get_standard_design_phrases()),
    ]:
        for keyword in keywords:
            rows = groups.get((analysis_type, keyword), [])
            summary_rows.append(
                {
                    "analysis_type": analysis_type,
                    "keyword": keyword,
                    "total_match_count": str(len(rows)),
                    "high_exposure_count": str(sum(1 for row in rows if row["is_high_exposure"] == "TRUE")),
                    "real_sales_count": str(sum(1 for row in rows if row["is_real_sales"] == "TRUE")),
                    "strong_signal_count": str(sum(1 for row in rows if row["is_strong_signal"] == "TRUE")),
                }
            )

    summary_rows.sort(
        key=lambda row: (
            row["analysis_type"],
            -parse_int(row["strong_signal_count"]),
            -parse_int(row["real_sales_count"]),
            -parse_int(row["high_exposure_count"]),
            row["keyword"],
        )
    )
    return summary_rows


def get_standard_design_phrases() -> list[str]:
    """获取与 V2.8 报告一致的设计短语标准口径。"""
    return sorted({normalize_design_phrase(phrase) for phrase in DESIGN_ELEMENT_PHRASES})


def build_audit_rows(products: list[dict[str, str]]) -> list[dict[str, str]]:
    """生成场景和设计元素匹配明细。"""
    standard_phrases = get_standard_design_phrases()
    audit_rows: list[dict[str, str]] = []

    for product in products:
        records = match_scenario_keywords(product)
        records.extend(match_design_elements(product, standard_phrases))
        audit_rows.extend(build_audit_row(record) for record in records)

    audit_rows.sort(
        key=lambda row: (
            row["analysis_type"],
            row["keyword"],
            parse_int(row["product_id"]),
        )
    )
    return audit_rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    """写入 utf-8-sig CSV，方便 Excel 打开。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """执行 V2.8A 匹配明细校验。"""
    products = read_products(INPUT_FILE)
    audit_rows = build_audit_rows(products)
    summary_rows = build_summary_rows(audit_rows)

    write_csv(AUDIT_OUTPUT_FILE, AUDIT_FIELDS, audit_rows)
    write_csv(SUMMARY_OUTPUT_FILE, SUMMARY_FIELDS, summary_rows)

    scenario_rows = [row for row in audit_rows if row["analysis_type"] == "scenario"]
    design_rows = [row for row in audit_rows if row["analysis_type"] == "design_element"]
    print("V2.8A 分类页信号匹配明细校验完成")
    print(f"输入商品数：{len(products)}")
    print(f"场景匹配明细行数：{len(scenario_rows)}")
    print(f"设计元素匹配明细行数：{len(design_rows)}")
    print(f"明细 CSV 保存路径：{AUDIT_OUTPUT_FILE}")
    print(f"汇总 CSV 保存路径：{SUMMARY_OUTPUT_FILE}")


if __name__ == "__main__":
    main()
