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
    print("\nTesting /api/proxy/generate-copy?shop=test-shop.myshopify.com...")
    payload = {
        "product_name": "Test Product",
        "japanese_description": "【特徴】美しいシルク。\n【サイズ】M",
        "category": "Clothing",
        "product_id": 12345,
        "target_locale": "en"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "http://localhost:8000/api/proxy/generate-copy?shop=test-shop.myshopify.com",
                json=payload
            )
            print(f"Status: {response.status_code}")
            try:
                print(f"Body: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
            except:
                print(f"Body: {response.text}")
        except Exception as e:
            print(f"Error: {e}")

async def main():
    await test_health()
    await test_generate_copy_mock()

if __name__ == "__main__":
    asyncio.run(main())
