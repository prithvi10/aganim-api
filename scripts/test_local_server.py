import httpx
import json
import asyncio

async def test_health():
    print("Testing /health endpoint...")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8000/health")
            print(f"Status: {response.status_code}")
            print(f"Body: {response.json()}")
        except Exception as e:
            print(f"Error: {e}")

async def test_generate_copy_mock():
    print("\nTesting /api/proxy/generate-copy?shop=dev-shop.myshopify.com (no Shopify save)...")
    payload = {
        "product_name": "Test Product",
        "japanese_description": "【特徴】美しいシルク。\n【サイズ】幅10cm×奥行5cm×高さ2cm、重量100g。",
        "category": "Clothing",
        "product_id": None,
        "target_locale": "en",
        "auto_convert_units": True,
        "tone_profile": "professional",
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "http://localhost:8000/api/proxy/generate-copy?shop=dev-shop.myshopify.com",
                json=payload
            )
            print(f"Status: {response.status_code}")
            try:
                body = response.json()
                data = body.get("data") if isinstance(body, dict) else None
                discovered = body.get("discovered_values") if isinstance(body, dict) else None
                print("Response keys:", sorted(list(body.keys())) if isinstance(body, dict) else type(body).__name__)
                if isinstance(data, dict):
                    print("data keys:", sorted(list(data.keys())))
                    print(
                        "field presence:",
                        {
                            "title": bool(str(data.get("title") or "").strip()),
                            "description_len": len(str(data.get("description") or "")),
                            "seo_title": bool(str(data.get("seo_title") or "").strip()),
                            "seo_description": bool(str(data.get("seo_description") or "").strip()),
                        },
                    )
                if isinstance(discovered, list):
                    print("discovered_values count:", len(discovered))
            except:
                print(f"Body: {response.text}")
        except Exception as e:
            print(f"Error: {e}")

async def main():
    await test_health()
    await test_generate_copy_mock()

if __name__ == "__main__":
    asyncio.run(main())
