"""Unit tests for bulk_upload_parser.py — CSV/ZIP parsing and validation."""
from __future__ import annotations

import io
import os
import csv
import zipfile
import tempfile
from typing import Optional

import pytest

from src.ecommerce.services.bulk_upload_parser import (
    parse_csv,
    parse_zip,
    parse_upload,
    BulkProductItem,
    MAX_PRODUCTS,
    REQUIRED_COLUMNS,
)

from fastapi import HTTPException


def _make_csv_bytes(rows, columns=None) -> bytes:
    """Helper to generate CSV bytes from a list of dicts."""
    if columns is None:
        columns = list(REQUIRED_COLUMNS)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _make_row(idx: int = 1, **overrides) -> dict:
    """Generate a single valid CSV row dict."""
    base = {
        "row_id": f"row_{idx}",
        "product_name_ja": f"商品{idx}",
        "description_ja": f"説明{idx}",
        "category": "General",
        "target_market": "en",
    }
    base.update(overrides)
    return base


def _make_zip_bytes(
    csv_bytes: bytes,
    images: dict[str, bytes] | None = None,
) -> bytes:
    """Create a ZIP archive with products.csv and optional images."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("products.csv", csv_bytes.decode("utf-8"))
        if images:
            for name, data in images.items():
                zf.writestr(f"images/{name}", data)
    return buf.getvalue()


# ── CSV Parsing ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_csv_happy_path():
    rows = [_make_row(i) for i in range(1, 6)]
    data = _make_csv_bytes(rows)
    items = await parse_csv(data, "text_only")
    assert len(items) == 5
    assert items[0].row_id == "row_1"
    assert items[0].product_name_ja == "商品1"


@pytest.mark.asyncio
async def test_csv_missing_required_column():
    data = b"row_id,product_name_ja,category,target_market\n1,A,B,en\n"
    with pytest.raises(HTTPException) as exc_info:
        await parse_csv(data, "text_only")
    assert exc_info.value.status_code == 422
    assert "description_ja" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_csv_extra_columns_ignored():
    columns = list(REQUIRED_COLUMNS) + ["price", "sku", "notes"]
    rows = [
        {**_make_row(1), "price": "100", "sku": "ABC", "notes": "ignore me"},
    ]
    data = _make_csv_bytes(rows, columns=columns)
    items = await parse_csv(data, "text_only")
    assert len(items) == 1
    assert items[0].row_id == "row_1"
    assert not hasattr(items[0], "price")


@pytest.mark.asyncio
async def test_csv_max_rows_exceeded():
    rows = [_make_row(i) for i in range(1, 12)]  # 11 rows
    data = _make_csv_bytes(rows)
    with pytest.raises(HTTPException) as exc_info:
        await parse_csv(data, "text_only")
    assert exc_info.value.status_code == 422
    assert "Maximum" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_csv_empty_file():
    data = b"row_id,product_name_ja,description_ja,category,target_market\n"
    with pytest.raises(HTTPException) as exc_info:
        await parse_csv(data, "text_only")
    assert exc_info.value.status_code == 422
    assert "no product rows" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_csv_utf8_japanese():
    rows = [
        _make_row(1, product_name_ja="備前焼の花瓶", description_ja="伝統的な日本の陶器です。窯で焼かれた美しい花瓶。"),
    ]
    data = _make_csv_bytes(rows)
    items = await parse_csv(data, "text_only")
    assert len(items) == 1
    assert "備前焼" in items[0].product_name_ja
    assert "陶器" in items[0].description_ja


# ── ZIP Parsing ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_zip_happy_path():
    columns = list(REQUIRED_COLUMNS) + ["image_ref"]
    rows = [
        {**_make_row(1), "image_ref": "IMG_001.jpg"},
        {**_make_row(2), "image_ref": "IMG_002.jpg"},
    ]
    csv_bytes = _make_csv_bytes(rows, columns=columns)
    images = {
        "IMG_001.jpg": b"\xff\xd8\xff\xe0fake-jpeg-1",
        "IMG_002.jpg": b"\xff\xd8\xff\xe0fake-jpeg-2",
    }
    zip_bytes = _make_zip_bytes(csv_bytes, images)

    items, temp_dir = await parse_zip(zip_bytes, "full_launch")
    try:
        assert len(items) == 2
        assert items[0].image_ref == "IMG_001.jpg"
        assert items[0].image_path is not None
        assert os.path.isfile(items[0].image_path)
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_zip_missing_products_csv():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "no csv here")
    with pytest.raises(HTTPException) as exc_info:
        await parse_zip(buf.getvalue(), "full_launch")
    assert exc_info.value.status_code == 422
    assert "products.csv" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_zip_missing_image_file():
    columns = list(REQUIRED_COLUMNS) + ["image_ref"]
    rows = [{**_make_row(1), "image_ref": "IMG_003.jpg"}]
    csv_bytes = _make_csv_bytes(rows, columns=columns)
    images = {"IMG_001.jpg": b"data"}  # IMG_003 not present
    zip_bytes = _make_zip_bytes(csv_bytes, images)

    with pytest.raises(HTTPException) as exc_info:
        await parse_zip(zip_bytes, "full_launch")
    assert exc_info.value.status_code == 422
    assert "IMG_003.jpg" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_zip_missing_image_ref_column():
    rows = [_make_row(1)]
    csv_bytes = _make_csv_bytes(rows)  # no image_ref column
    zip_bytes = _make_zip_bytes(csv_bytes)

    with pytest.raises(HTTPException) as exc_info:
        await parse_zip(zip_bytes, "full_launch")
    assert exc_info.value.status_code == 422
    assert "image_ref" in str(exc_info.value.detail)


# ── parse_upload dispatch ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_upload_csv():
    rows = [_make_row(1)]
    data = _make_csv_bytes(rows)
    items, temp_dir = await parse_upload(data, "products.csv", "text_only")
    assert len(items) == 1
    assert temp_dir is None


@pytest.mark.asyncio
async def test_parse_upload_unsupported_type():
    with pytest.raises(HTTPException) as exc_info:
        await parse_upload(b"data", "file.xlsx", "text_only")
    assert exc_info.value.status_code == 422
    assert "Unsupported" in str(exc_info.value.detail)
