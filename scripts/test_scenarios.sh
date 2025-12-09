#!/bin/bash

# Configuration
API_URL="http://localhost:8000"
ADMIN_TOKEN="dev-token-123"

# Define Users to Test
# Format: "Token|Description|ExpectStreamingSuccess"
# ExpectStreamingSuccess: true/false
USERS=(
    "dev-token-123|Standard Dev User (50k quota)|true"
    "restricted-token-456|Restricted User (100 quota, No Stream)|false"
)

echo "=============================================="
echo "🧪 STARTING MODULAR SCENARIO TESTS"
echo "Target: $API_URL"
echo "=============================================="

# Function to run tests for a specific user
run_user_tests() {
    local API_KEY=$1
    local USER_DESC=$2
    local CAN_STREAM=$3

    echo -e "\n------------------------------------------------------------"
    echo "👤 TESTING USER: $USER_DESC"
    echo "🔑 API Key: $API_KEY"
    echo "🌊 Can Stream: $CAN_STREAM"
    echo "------------------------------------------------------------"

    # 1. HAPPY PATH: Standard Generation
    echo -e "\n🔹 [Happy Path] Standard Copy Generation"
    curl -s -X POST "$API_URL/api/generate-copy" \
      -H "Authorization: Bearer $API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "product_name": "一点物・昭和レトロ】正絹 訪問着（ほうもんぎ）- 寿ぎの鶴亀模様",
        "category": "General",
        "japanese_description": "商品タイトル	【一点物・昭和レトロ】正絹 訪問着（ほうもんぎ）- 寿ぎの鶴亀模様\n商品説明	纏う芸術品： 昭和時代に丁寧に織り上げられた、**正絹（しょうけん）**のアンティーク訪問着です。着物全体に広がる柄は、鶴亀（つるかめ）という日本で長寿と慶びを象徴する大変縁起の良い吉祥文様であり、その繊細な刺繍はまさに芸術。\n状態	古着としての美品(コンディションA) 日本国内の専門オークションより厳選して仕入れた、次世代へ繋ぐリユース品です。目立たない程度の経年劣化はございますが、着用には全く問題なく、当時の鮮やかな色彩を保っています。\nスタイリング	伝統的なフォーマルな場はもちろん、ベルト（帯）を締めてモダンなガウンコートや羽織として日常のファッションに取り入れることで、唯一無二の存在感を放ちます。",
        "stream": false
      }' | python3 -m json.tool

    # 2. STREAMING TEST (Conditional)
    if [ "$CAN_STREAM" == "true" ]; then
        echo -e "\n🔹 [Happy Path] Streaming Copy Generation (Should SUCCEED)"
        curl -N -X POST "$API_URL/api/generate-copy" \
          -H "Authorization: Bearer $API_KEY" \
          -H "Content-Type: application/json" \
          -d '{
            "product_name": "Stream Item",
            "category": "General",
            "japanese_description": "\n商品タイトル\t【本場・常滑焼】横手急須(300ml)- 日本の緑茶を極めるための逸品\n商品説明\t日常の儀式を格上げする： この急須は、日本茶を淹れるのに欠かせない横手（よこで）スタイルで、特に煎茶や玉露の風味を最大限に引き出すように設計されています。愛知県常滑の伝統を受け継ぐ職人が一つひとつ手作業で仕上げた、日本六古窯の技術が詰まった逸品です。\n機能\t目詰まりしない特製メッシュ： 特徴的なのは、注ぎ口に組み込まれた極めて目の細かい**帯アミ（おびあみ）**フィルターです。これにより、深蒸し茶など細かな茶葉でも詰まることなく、最後までクリアで雑味のないお茶を注ぎ切ることができます。\n素材\t鉄分を豊富に含む常滑の朱泥（しゅでい）土を使用しており、この素材が持つ自然な作用によりお湯がまろやかになり、茶葉本来の旨味を深めます。ご使用後は水洗いをおすすめします。",
            "stream": true
          }'
        echo "" 
    else
        echo -e "\n🔻 [Unhappy Path] Streaming Copy Generation (Should FAIL 403)"
        curl -s -X POST "$API_URL/api/generate-copy" \
          -H "Authorization: Bearer $API_KEY" \
          -H "Content-Type: application/json" \
          -d '{
            "product_name": "Stream Forbidden Item",
            "category": "General",
            "japanese_description": "Should be blocked.",
            "stream": true
          }' | python3 -m json.tool
    fi

    # 3. RATE LIMIT / EDGE CASE
    # We send a small burst to see behavior (won't necessarily hit limit for dev user, might for restricted)
    echo -e "\n🔸 [Edge Case] Sending Burst of 3 Requests"
    for i in {1..3}; do
       echo -n "Req $i: "
       curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/api/generate-copy" \
         -H "Authorization: Bearer $API_KEY" \
         -H "Content-Type: application/json" \
         -d '{
           "product_name": "Burst Item", 
           "category": "Misc", 
           "japanese_description": "Burst test.",
           "stream": false
         }'
       echo ""
    done
}

# ----------------------------------------------------
# A. GLOBAL TESTS (Admin, Invalid Key, etc.)
# ----------------------------------------------------
echo -e "\n🌍 [Global] Admin Auth Check"
curl -s -X GET "$API_URL/api/admin/me" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" | python3 -m json.tool

echo -e "\n🌍 [Global] Invalid API Key Check"
curl -s -X POST "$API_URL/api/generate-copy" \
  -H "Authorization: Bearer INVALID_KEY_999" \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "Secret Item",
    "japanese_description": "Hidden text",
    "category": "Misc"
  }' | python3 -m json.tool

echo -e "\n🌍 [Global] Missing Authorization Header Check (401)"
curl -s -X POST "$API_URL/api/generate-copy" \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "No Auth Item",
    "japanese_description": "Should fail",
    "category": "Misc"
  }' | python3 -m json.tool

echo -e "\n🌍 [Global] Validation: Whitespace Description (422)"
curl -s -X POST "$API_URL/api/generate-copy" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "Empty Item",
    "japanese_description": "   ",
    "category": "Misc"
  }' | python3 -m json.tool

echo -e "\n🌍 [Global] Validation: Description Too Long (422)"
# Generate a long string (>5000 chars)
LONG_DESC=$(printf 'a%.0s' {1..5005})
curl -s -X POST "$API_URL/api/generate-copy" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"product_name\": \"Long Item\",
    \"japanese_description\": \"$LONG_DESC\",
    \"category\": \"Misc\"
  }" | python3 -m json.tool

# ----------------------------------------------------
# B. PER-USER TESTS
# ----------------------------------------------------
for user_entry in "${USERS[@]}"; do
    IFS="|" read -r KEY DESC CAN_STREAM <<< "$user_entry"
    run_user_tests "$KEY" "$DESC" "$CAN_STREAM"
done

echo -e "\n✅ All Scenarios Completed."
