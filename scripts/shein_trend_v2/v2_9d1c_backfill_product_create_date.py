"""Backfill product creation dates in the V2.9D1C detail checkpoint CSV."""

from __future__ import annotations

import csv
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "output"
    / "v2_9d1c_detail_attributes_checkpoint_clean_urls.csv"
)
PRODUCT_CREATE_DATE_FIELDS = [
    "product_create_date",
    "product_create_date_digits",
    "product_create_date_parse_status",
    "product_create_date_parse_reason",
]


def infer_product_create_date_from_sku(sku: Any) -> dict[str, str]:
    """Infer a product creation date from a detail-page SKU."""
    result = {
        "product_create_date": "",
        "product_create_date_digits": "",
        "product_create_date_parse_status": "failed",
        "product_create_date_parse_reason": "",
    }

    sku_text = str(sku or "").strip()
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


def build_output_fieldnames(fieldnames: list[str]) -> list[str]:
    """Place the backfill fields immediately after sku without duplicates."""
    if "sku" not in fieldnames:
        raise ValueError("CSV 表头中缺少 sku 字段")

    output_fieldnames = [
        field for field in fieldnames if field not in PRODUCT_CREATE_DATE_FIELDS
    ]
    sku_index = output_fieldnames.index("sku")
    output_fieldnames[sku_index + 1 : sku_index + 1] = PRODUCT_CREATE_DATE_FIELDS
    return output_fieldnames


def build_backup_path(output_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_path.with_name(f"{output_path.stem}.backup_{timestamp}.csv")


def main() -> None:
    if not OUTPUT_PATH.exists():
        raise FileNotFoundError(f"源 CSV 不存在：{OUTPUT_PATH}")

    with OUTPUT_PATH.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError(f"源 CSV 缺少表头：{OUTPUT_PATH}")
        fieldnames = build_output_fieldnames(reader.fieldnames)
        rows = list(reader)

    backup_path = build_backup_path(OUTPUT_PATH)
    if backup_path.exists():
        raise FileExistsError(f"备份文件已存在，请稍后重试：{backup_path}")
    shutil.copy2(OUTPUT_PATH, backup_path)

    success_count = 0
    failed_count = 0
    empty_sku_count = 0

    for row in rows:
        sku = str(row.get("sku") or "").strip()
        if not sku:
            empty_sku_count += 1

        create_date_fields = infer_product_create_date_from_sku(sku)
        row.update(create_date_fields)
        if create_date_fields["product_create_date_parse_status"] == "success":
            success_count += 1
        else:
            failed_count += 1

    temp_path = OUTPUT_PATH.with_suffix(f"{OUTPUT_PATH.suffix}.backfill.tmp")
    try:
        with temp_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=fieldnames,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)
            csv_file.flush()
            os.fsync(csv_file.fileno())
        os.replace(temp_path, OUTPUT_PATH)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    print(f"total_rows: {len(rows)}")
    print(f"success_count: {success_count}")
    print(f"failed_count: {failed_count}")
    print(f"empty_sku_count: {empty_sku_count}")
    print(f"backup_path: {backup_path}")
    print(f"output_path: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
