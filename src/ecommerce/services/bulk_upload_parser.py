"""
CSV/ZIP parser for Bulk Upload Missions.

Parses and validates merchant-uploaded files containing up to 10 products
for bulk inventory creation.
"""
from __future__ import annotations

import csv
import io
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

REQUIRED_COLUMNS = {"row_id", "product_name_ja", "description_ja", "category", "target_market"}
MAX_PRODUCTS = 10


@dataclass
class BulkProductItem:
    row_id: str
    product_name_ja: str
    description_ja: str
    category: str
    target_market: str
    image_ref: Optional[str] = None
    image_path: Optional[str] = None


def _parse_csv_rows(reader: csv.DictReader, mission_type: str) -> list[BulkProductItem]:
    """Validate headers and extract rows from a DictReader."""
    if reader.fieldnames is None:
        raise HTTPException(status_code=422, detail="CSV contains no header row.")

    headers = set(reader.fieldnames)
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"CSV is missing required column(s): {', '.join(sorted(missing))}",
        )

    if mission_type == "full_launch" and "image_ref" not in headers:
        raise HTTPException(
            status_code=422,
            detail="CSV must include an 'image_ref' column for full_launch missions.",
        )

    items: list[BulkProductItem] = []
    for idx, row in enumerate(reader, start=1):
        if idx > MAX_PRODUCTS:
            raise HTTPException(
                status_code=422,
                detail=f"Maximum {MAX_PRODUCTS} products per upload. CSV has more than {MAX_PRODUCTS} rows.",
            )
        items.append(
            BulkProductItem(
                row_id=row.get("row_id", "").strip(),
                product_name_ja=row.get("product_name_ja", "").strip(),
                description_ja=row.get("description_ja", "").strip(),
                category=row.get("category", "").strip(),
                target_market=row.get("target_market", "").strip(),
                image_ref=row.get("image_ref", "").strip() or None,
            )
        )

    if not items:
        raise HTTPException(status_code=422, detail="CSV contains no product rows.")

    return items


async def parse_csv(file_bytes: bytes, mission_type: str) -> list[BulkProductItem]:
    """Parse a standalone CSV file."""
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    return _parse_csv_rows(reader, mission_type)


async def parse_zip(
    file_bytes: bytes, mission_type: str
) -> tuple[list[BulkProductItem], str]:
    """
    Parse a ZIP containing products.csv and an images/ folder.

    Returns (items, temp_dir) where temp_dir holds extracted images.
    The caller is responsible for cleaning up temp_dir.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="Uploaded file is not a valid ZIP archive.")

    names = zf.namelist()

    csv_name = None
    for name in names:
        basename = os.path.basename(name)
        if basename.lower() == "products.csv":
            csv_name = name
            break

    if csv_name is None:
        raise HTTPException(
            status_code=422,
            detail="ZIP must contain a 'products.csv' file.",
        )

    temp_dir = tempfile.mkdtemp(prefix="bulk_upload_")
    zf.extractall(temp_dir)

    csv_path = os.path.join(temp_dir, csv_name)
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        items = _parse_csv_rows(reader, mission_type)

    # Validate image references exist on disk
    if mission_type == "full_launch":
        images_dir = os.path.join(temp_dir, "images")
        if not os.path.isdir(images_dir):
            # Try top-level extraction (some ZIPs nest under a root folder)
            for entry in os.listdir(temp_dir):
                candidate = os.path.join(temp_dir, entry, "images")
                if os.path.isdir(candidate):
                    images_dir = candidate
                    break

        for item in items:
            if not item.image_ref:
                raise HTTPException(
                    status_code=422,
                    detail=f"Row '{item.row_id}' is missing an image_ref value.",
                )
            img_path = os.path.join(images_dir, item.image_ref)
            if not os.path.isfile(img_path):
                raise HTTPException(
                    status_code=422,
                    detail=f"Image file '{item.image_ref}' referenced in row '{item.row_id}' not found in images/ folder.",
                )
            item.image_path = img_path

    return items, temp_dir


async def parse_upload(
    file_bytes: bytes, filename: str, mission_type: str
) -> tuple[list[BulkProductItem], Optional[str]]:
    """
    Detect file type and parse accordingly.

    Returns (items, temp_dir_or_none). temp_dir is only set for ZIP uploads.
    """
    lower = filename.lower()
    if lower.endswith(".zip"):
        return await parse_zip(file_bytes, mission_type)
    elif lower.endswith(".csv"):
        items = await parse_csv(file_bytes, mission_type)
        return items, None
    else:
        raise HTTPException(
            status_code=422,
            detail="Unsupported file type. Please upload a .csv or .zip file.",
        )
