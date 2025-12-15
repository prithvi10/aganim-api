#!/bin/bash

# Configuration
API_URL="http://localhost:8001"
ADMIN_TOKEN="dev-token-123"

# Define Users to Test
# Format: "ShopDomain|Description|ExpectStreamingSuccess"
USERS=(
    "dev-shop.myshopify.com|Standard Dev Shop (50k quota)|true"
)

echo "=============================================="
echo "🧪 STARTING MODULAR SCENARIO TESTS (PROXY FLOW)"
echo "Target: $API_URL"
echo "=============================================="

# Function to run tests for a specific user
run_user_tests() {
    local SHOP_DOMAIN=$1
    local USER_DESC=$2
    local CAN_STREAM=$3

    echo -e "\n------------------------------------------------------------"
    echo "👤 TESTING SHOP: $USER_DESC"
    echo "🏪 Domain: $SHOP_DOMAIN"
    echo "🌊 Can Stream: $CAN_STREAM"
    echo "------------------------------------------------------------"

    # 1. HAPPY PATH: Standard Generation via Proxy
    echo -e "\n🔹 [Happy Path] Standard Copy Generation (Proxy)"
    
    # Use printf to format JSON properly
    JSON_BODY=$(printf '{
        "product_name": "一点物・昭和レトロ】正絹 訪問着（ほうもんぎ）- 寿ぎの鶴亀模様",
        "category": "General",
        "japanese_description": "商品タイトル\\t【一点物・昭和レトロ】正絹 訪問着（ほうもんぎ）- 寿ぎの鶴亀模様\\n商品説明\\t纏う芸術品： 昭和時代に丁寧に織り上げられた、**正絹（しょうけん）**のアンティーク訪問着です。",
        "stream": false
      }')

    # Call Proxy Endpoint with shop param
    # Note: In real app, HMAC validation is on. Locally, we might need to bypass or mock it.
    # Assuming local env allows this or we have valid data.
    # If the app enforces HMAC, this script might fail unless we generate a signature.
    # For now, we assume the previous "remove dependencies" step made it testable or we accept 401 if HMAC is enforced.
    
    curl -s -X POST "$API_URL/api/proxy/generate-copy?shop=$SHOP_DOMAIN" \
      -H "Content-Type: application/json" \
      -d "$JSON_BODY" | python3 -m json.tool

    # 2. STREAMING TEST
    if [ "$CAN_STREAM" == "true" ]; then
        echo -e "\n🔹 [Happy Path] Streaming Copy Generation (Should SUCCEED)"
        JSON_STREAM_BODY=$(printf '{
            "product_name": "Stream Item",
            "category": "General",
            "japanese_description": "Streaming test description.",
            "stream": true
          }')
        
        # Streaming response might not be JSON compatible for json.tool
        curl -N -X POST "$API_URL/api/proxy/generate-copy?shop=$SHOP_DOMAIN" \
          -H "Content-Type: application/json" \
          -d "$JSON_STREAM_BODY"
        echo "" 
    fi
}

# ----------------------------------------------------
# A. GLOBAL TESTS
# ----------------------------------------------------
echo -e "\n🌍 [Global] Missing Shop Parameter Check (400)"
curl -s -X POST "$API_URL/api/proxy/generate-copy" \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "No Shop Item",
    "japanese_description": "Should fail",
    "category": "Misc"
  }' | python3 -m json.tool

echo -e "\n🌍 [Global] Validation: Whitespace Description (422)"
curl -s -X POST "$API_URL/api/proxy/generate-copy?shop=dev-shop.myshopify.com" \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "Empty Item",
    "japanese_description": "   ",
    "category": "Misc"
  }' | python3 -m json.tool

# ----------------------------------------------------
# B. PER-USER TESTS
# ----------------------------------------------------
for user_entry in "${USERS[@]}"; do
    IFS="|" read -r SHOP DESC CAN_STREAM <<< "$user_entry"
    run_user_tests "$SHOP" "$DESC" "$CAN_STREAM"
done

echo -e "\n✅ All Scenarios Completed."
