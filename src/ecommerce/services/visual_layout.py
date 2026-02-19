"""
visual_layout -- Object splitting and auto-layout for product ad compositing.

Provides:
1. ``split_objects``: connected-components labelling on the alpha channel to
   extract individual product cutouts from an isolated RGBA image.
2. ``auto_layout``: deterministic layout templates that return placement
   coordinates for 1–6 objects on a 1024x1024 canvas.
3. ``composite_and_mask``: pastes objects onto a canvas and generates the
   Flux Fill binary mask (0 = product / keep, 255 = background / inpaint).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import List, Tuple

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ObjectCutout:
    """A single product object extracted from an isolated RGBA image."""
    rgba_bytes: bytes
    width: int
    height: int
    area: int


@dataclass
class PlacementSlot:
    """Where to place an object on the canvas."""
    scale: float
    x: int
    y: int
    z_order: int = 0


# ---------------------------------------------------------------------------
# 1. Object splitting (connected-components on alpha)
# ---------------------------------------------------------------------------

_ALPHA_THRESHOLD = 30
_MIN_OBJECT_AREA = 500


def split_objects(isolated_rgba_bytes: bytes) -> List[ObjectCutout]:
    """Split an RGBA image into individual product cutouts.

    Uses connected-components labelling on the alpha channel.  Objects smaller
    than ``_MIN_OBJECT_AREA`` pixels are discarded (noise / fragments).

    Falls back to treating the entire image as one object when scipy is
    unavailable or only one component is found.
    """
    from PIL import Image as PILImage
    import numpy as np

    img = PILImage.open(io.BytesIO(isolated_rgba_bytes)).convert("RGBA")
    alpha = np.array(img.getchannel("A"))
    binary = (alpha > _ALPHA_THRESHOLD).astype(np.uint8)

    try:
        from scipy import ndimage
        labelled, n_labels = ndimage.label(binary)
    except ImportError:
        logger.warning("[visual_layout] scipy not installed; treating as single object")
        return [_whole_image_cutout(img)]

    if n_labels <= 1:
        return [_whole_image_cutout(img)]

    cutouts: List[ObjectCutout] = []
    img_array = np.array(img)

    for label_id in range(1, n_labels + 1):
        ys, xs = np.where(labelled == label_id)
        area = len(ys)
        if area < _MIN_OBJECT_AREA:
            continue

        y_min, y_max = int(ys.min()), int(ys.max()) + 1
        x_min, x_max = int(xs.min()), int(xs.max()) + 1

        crop = img_array[y_min:y_max, x_min:x_max].copy()
        mask_crop = (labelled[y_min:y_max, x_min:x_max] == label_id)
        crop[~mask_crop] = [0, 0, 0, 0]

        crop_img = PILImage.fromarray(crop, "RGBA")
        buf = io.BytesIO()
        crop_img.save(buf, "PNG")
        cutouts.append(ObjectCutout(
            rgba_bytes=buf.getvalue(),
            width=crop_img.width,
            height=crop_img.height,
            area=area,
        ))

    if not cutouts:
        return [_whole_image_cutout(img)]

    cutouts.sort(key=lambda c: c.area, reverse=True)
    logger.info("[visual_layout] split_objects found %d objects", len(cutouts))
    return cutouts


def _whole_image_cutout(img) -> ObjectCutout:
    """Wrap the entire RGBA image as a single ObjectCutout."""
    import numpy as np
    buf = io.BytesIO()
    img.save(buf, "PNG")
    alpha = np.array(img.getchannel("A"))
    return ObjectCutout(
        rgba_bytes=buf.getvalue(),
        width=img.width,
        height=img.height,
        area=int((alpha > _ALPHA_THRESHOLD).sum()),
    )


# ---------------------------------------------------------------------------
# 2. Auto layout templates
# ---------------------------------------------------------------------------

def auto_layout(
    cutouts: List[ObjectCutout],
    canvas_size: int = 1024,
) -> List[PlacementSlot]:
    """Return placement slots for each cutout on a square canvas.

    Templates are chosen by number of objects:
    - 1: HeroCenter
    - 2: DuoOffset
    - 3: TrioArc
    - 4-6: ShelfGrid
    """
    n = len(cutouts)
    if n == 0:
        return []
    if n == 1:
        return _layout_hero_center(cutouts, canvas_size)
    if n == 2:
        return _layout_duo_offset(cutouts, canvas_size)
    if n == 3:
        return _layout_trio_arc(cutouts, canvas_size)
    return _layout_shelf_grid(cutouts, canvas_size)


def _layout_hero_center(
    cutouts: List[ObjectCutout], cs: int,
) -> List[PlacementSlot]:
    c = cutouts[0]
    scale = _fit_scale(c.width, c.height, int(cs * 0.70))
    w, h = int(c.width * scale), int(c.height * scale)
    return [PlacementSlot(scale=scale, x=(cs - w) // 2, y=(cs - h) // 2, z_order=0)]


def _layout_duo_offset(
    cutouts: List[ObjectCutout], cs: int,
) -> List[PlacementSlot]:
    slots = []
    max_dim = int(cs * 0.55)
    for i, c in enumerate(cutouts[:2]):
        scale = _fit_scale(c.width, c.height, max_dim)
        w, h = int(c.width * scale), int(c.height * scale)
        x_offset = int(cs * 0.15) if i == 0 else int(cs * 0.45)
        y_center = (cs - h) // 2 + (10 if i == 0 else -10)
        slots.append(PlacementSlot(scale=scale, x=x_offset, y=y_center, z_order=i))
    return slots


def _layout_trio_arc(
    cutouts: List[ObjectCutout], cs: int,
) -> List[PlacementSlot]:
    """Center hero in front, two flanking behind."""
    slots = []
    hero = cutouts[0]
    hero_scale = _fit_scale(hero.width, hero.height, int(cs * 0.55))
    hw, hh = int(hero.width * hero_scale), int(hero.height * hero_scale)
    slots.append(PlacementSlot(
        scale=hero_scale,
        x=(cs - hw) // 2,
        y=cs - hh - int(cs * 0.08),
        z_order=2,
    ))

    back_max = int(cs * 0.45)
    positions = [(int(cs * 0.05), int(cs * 0.10)), (int(cs * 0.55), int(cs * 0.10))]
    for i, c in enumerate(cutouts[1:3]):
        scale = _fit_scale(c.width, c.height, back_max)
        slots.append(PlacementSlot(
            scale=scale, x=positions[i][0], y=positions[i][1], z_order=i,
        ))
    return slots


def _layout_shelf_grid(
    cutouts: List[ObjectCutout], cs: int,
) -> List[PlacementSlot]:
    """2-row shelf: back row smaller, front row larger."""
    n = len(cutouts)
    back_count = n // 2
    front_count = n - back_count

    slots = []
    back_max = int(cs * 0.35)
    front_max = int(cs * 0.45)

    for row, (count, max_dim, y_base, z_base) in enumerate([
        (back_count, back_max, int(cs * 0.05), 0),
        (front_count, front_max, int(cs * 0.45), back_count),
    ]):
        start_idx = 0 if row == 0 else back_count
        spacing = cs // (count + 1)
        for j in range(count):
            c = cutouts[start_idx + j]
            scale = _fit_scale(c.width, c.height, max_dim)
            w = int(c.width * scale)
            x = spacing * (j + 1) - w // 2
            slots.append(PlacementSlot(
                scale=scale, x=x, y=y_base, z_order=z_base + j,
            ))
    return slots


def _fit_scale(w: int, h: int, max_dim: int) -> float:
    return min(max_dim / max(w, 1), max_dim / max(h, 1))


# ---------------------------------------------------------------------------
# 3. Composite + mask generation
# ---------------------------------------------------------------------------

def composite_and_mask(
    cutouts: List[ObjectCutout],
    slots: List[PlacementSlot],
    canvas_size: int = 1024,
) -> Tuple[bytes, bytes]:
    """Paste cutouts onto a canvas and generate the binary inpainting mask.

    Returns:
        (canvas_png_bytes, mask_png_bytes)
        Mask: 0 = product (keep), 255 = background (inpaint).
    """
    from PIL import Image as PILImage, ImageChops

    canvas = PILImage.new("RGB", (canvas_size, canvas_size), (255, 255, 255))
    mask = PILImage.new("L", (canvas_size, canvas_size), 255)

    ordered = sorted(zip(cutouts, slots), key=lambda pair: pair[1].z_order)

    for cutout, slot in ordered:
        obj = PILImage.open(io.BytesIO(cutout.rgba_bytes)).convert("RGBA")
        new_w = max(1, int(obj.width * slot.scale))
        new_h = max(1, int(obj.height * slot.scale))
        obj = obj.resize((new_w, new_h), PILImage.LANCZOS)

        canvas.paste(obj, (slot.x, slot.y), obj)

        alpha = obj.getchannel("A")
        binary_alpha = alpha.point(lambda px: 255 if px > _ALPHA_THRESHOLD else 0)
        product_stamp = PILImage.new("L", (canvas_size, canvas_size), 0)
        product_stamp.paste(binary_alpha, (slot.x, slot.y))
        mask = ImageChops.subtract(mask, product_stamp)

    canvas_buf = io.BytesIO()
    canvas.save(canvas_buf, "PNG")
    mask_buf = io.BytesIO()
    mask.save(mask_buf, "PNG")

    logger.info(
        "[visual_layout] composite_and_mask objects=%d canvas=%dx%d",
        len(cutouts), canvas_size, canvas_size,
    )
    return canvas_buf.getvalue(), mask_buf.getvalue()
