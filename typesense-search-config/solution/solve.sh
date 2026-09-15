#!/bin/bash

API_KEY="typesense_bench_admin_key"
BASE="http://localhost:8108"
TS="/usr/local/bin/typesense-server"

# Start Typesense if not running
if ! curl -sf "$BASE/health" > /dev/null 2>&1; then
    mkdir -p /app/typesense-data
    "$TS" --data-dir=/app/typesense-data --api-key="$API_KEY" --enable-cors > /tmp/typesense.log 2>&1 &
    disown

    STARTED=false
    for i in $(seq 1 45); do
        if curl -sf "$BASE/health" > /dev/null 2>&1; then
            STARTED=true
            break
        fi
        sleep 1
    done

    if [ "$STARTED" != "true" ]; then
        echo "First start failed, trying fresh data directory..."
        pkill -f typesense-server 2>/dev/null
        sleep 2
        rm -rf /app/typesense-data
        mkdir -p /app/typesense-data
        "$TS" --data-dir=/app/typesense-data --api-key="$API_KEY" --enable-cors > /tmp/typesense.log 2>&1 &
        disown
        for i in $(seq 1 45); do
            if curl -sf "$BASE/health" > /dev/null 2>&1; then
                STARTED=true
                break
            fi
            sleep 1
        done
    fi

    if [ "$STARTED" != "true" ]; then
        echo "ERROR: Typesense failed to start"
        cat /tmp/typesense.log 2>/dev/null | tail -30
        exit 1
    fi
    echo "Typesense ready."
fi

echo "=== Rebuilding collections with correct schemas ==="

# Delete existing collections (order: reviews references products, products references brands)
for coll in reviews products brands; do
    curl -s "$BASE/collections/$coll" -X DELETE -H "X-TYPESENSE-API-KEY: $API_KEY" > /dev/null 2>&1
done

# Create brands collection
curl -s "$BASE/collections" -X POST \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"name":"brands","fields":[{"name":"name","type":"string"},{"name":"country","type":"string","facet":true},{"name":"is_premium","type":"bool","facet":true}]}'
echo ""

# Create products with correct schema: reference on brand_id, geopoint for location, facet on category
curl -s "$BASE/collections" -X POST \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"name":"products","fields":[{"name":"title","type":"string"},{"name":"description","type":"string"},{"name":"price","type":"float"},{"name":"category","type":"string","facet":true},{"name":"brand_id","type":"string","reference":"brands.id"},{"name":"in_stock","type":"bool","facet":true},{"name":"location","type":"geopoint"},{"name":"tags","type":"string[]","facet":true}],"default_sorting_field":"price"}'
echo ""

# Create reviews with correct reference on product_id
curl -s "$BASE/collections" -X POST \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"name":"reviews","fields":[{"name":"product_id","type":"string","reference":"products.id"},{"name":"rating","type":"int32","facet":true},{"name":"text","type":"string"},{"name":"user_id","type":"string"}]}'
echo ""

# Import data
curl -s "$BASE/collections/brands/documents/import?action=create" -X POST \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    --data-binary @/app/data/brands.jsonl
echo ""
curl -s "$BASE/collections/products/documents/import?action=create" -X POST \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    --data-binary @/app/data/products.jsonl
echo ""
curl -s "$BASE/collections/reviews/documents/import?action=create" -X POST \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    --data-binary @/app/data/reviews.jsonl
echo ""

# Set up correct synonyms: laptop/notebook/portable computer as multi-way
curl -s "$BASE/collections/products/synonyms/laptop_synonyms" -X PUT \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"synonyms":["laptop","notebook","portable computer"]}'
echo ""

# Set up correct synonym: mobile -> phone/smartphone as one-way
curl -s "$BASE/collections/products/synonyms/mobile_synonym" -X PUT \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"root":"mobile","synonyms":["phone","smartphone"]}'
echo ""

# Set up correct curation override with exact match
curl -s "$BASE/collections/products/overrides/featured_override" -X PUT \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"rule":{"query":"featured","match":"exact"},"includes":[{"id":"prod_5","position":1}],"excludes":[{"id":"prod_4"}]}'
echo ""

# Delete any existing non-admin API keys
KEYS_JSON=$(curl -s "$BASE/keys" -H "X-TYPESENSE-API-KEY: $API_KEY")
KEY_IDS=$(echo "$KEYS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for k in data.get('keys', []):
    if k.get('id', 0) != 0:
        print(k['id'])
" 2>/dev/null)

for kid in $KEY_IDS; do
    curl -s "$BASE/keys/$kid" -X DELETE -H "X-TYPESENSE-API-KEY: $API_KEY" > /dev/null
done

# Create properly scoped search-only key for products collection only
KEY_RESP=$(curl -s "$BASE/keys" -X POST \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"description":"Search-only key for products","actions":["documents:search"],"collections":["products"]}')
KEY_VALUE=$(echo "$KEY_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['value'])")
echo "$KEY_VALUE" > /app/search_only_key.txt

echo "=== All fixes applied ==="
