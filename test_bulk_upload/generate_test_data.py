"""
Generate placeholder product images and the ready-to-upload ZIP for testing
bulk upload in production. Run once, then use the generated files.

    python test_bulk_upload/generate_test_data.py
"""
import os
import zipfile
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE, "full_launch", "images")
os.makedirs(IMG_DIR, exist_ok=True)

PRODUCTS = [
    ("matcha_powder.jpg",  (80, 140, 70),   "抹茶パウダー"),
    ("chopstick_set.jpg",  (139, 90, 43),   "箸セット"),
    ("arita_bowl.jpg",     (50, 80, 160),   "有田焼 茶碗"),
    ("furoshiki.jpg",      (180, 50, 80),   "風呂敷"),
    ("maneki_neko.jpg",    (200, 170, 50),  "招き猫"),
]

WIDTH, HEIGHT = 800, 800

for filename, bg_color, label in PRODUCTS:
    img = Image.new("RGB", (WIDTH, HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 48)
    except (OSError, IOError):
        font = ImageFont.load_default()

    draw.text(
        (WIDTH // 2, HEIGHT // 2 - 60),
        label,
        fill=(255, 255, 255),
        font=font,
        anchor="mm",
    )
    draw.text(
        (WIDTH // 2, HEIGHT // 2 + 20),
        "TEST IMAGE",
        fill=(255, 255, 255, 180),
        font=font,
        anchor="mm",
    )

    path = os.path.join(IMG_DIR, filename)
    img.save(path, "JPEG", quality=85)
    print(f"  Created {path} ({os.path.getsize(path):,} bytes)")

zip_path = os.path.join(BASE, "full_launch_upload.zip")
csv_path = os.path.join(BASE, "full_launch", "products.csv")

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write(csv_path, "products.csv")
    for fname in os.listdir(IMG_DIR):
        fpath = os.path.join(IMG_DIR, fname)
        zf.write(fpath, f"images/{fname}")

print(f"\n  ZIP created: {zip_path} ({os.path.getsize(zip_path):,} bytes)")
print("\nDone! Files ready for upload:")
print(f"  Text-only CSV : {os.path.join(BASE, 'text_only', 'products.csv')}")
print(f"  Full-launch ZIP: {zip_path}")
