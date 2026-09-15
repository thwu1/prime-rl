#!/bin/bash
# Initialize Typesense with intentionally broken configuration
API_KEY="typesense_bench_admin_key"
BASE="http://localhost:8108"
TS="/usr/local/bin/typesense-server"

"$TS" --data-dir=/app/typesense-data --api-key="$API_KEY" --enable-cors &
SERVER_PID=$!

for i in $(seq 1 60); do
    if curl -sf "$BASE/health" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! curl -sf "$BASE/health" > /dev/null 2>&1; then
    echo "ERROR: Typesense failed to start"
    exit 1
fi

echo "Typesense started, creating broken collections..."

# brands collection (correct schema — no defects here)
curl -sf "$BASE/collections" -X POST \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"name":"brands","fields":[{"name":"name","type":"string"},{"name":"country","type":"string","facet":true},{"name":"is_premium","type":"bool","facet":true}]}'
echo ""

# products: BROKEN — brand_id is plain string (no reference), location is float[] (not geopoint), category is not facetable
curl -sf "$BASE/collections" -X POST \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"name":"products","fields":[{"name":"title","type":"string"},{"name":"description","type":"string"},{"name":"price","type":"float"},{"name":"category","type":"string"},{"name":"brand_id","type":"string"},{"name":"in_stock","type":"bool","facet":true},{"name":"location","type":"float[]"},{"name":"tags","type":"string[]","facet":true}],"default_sorting_field":"price"}'
echo ""

# reviews: BROKEN — product_id is plain string (no reference)
curl -sf "$BASE/collections" -X POST \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"name":"reviews","fields":[{"name":"product_id","type":"string"},{"name":"rating","type":"int32","facet":true},{"name":"text","type":"string"},{"name":"user_id","type":"string"}]}'
echo ""

# Import data
curl -sf "$BASE/collections/brands/documents/import?action=create" -X POST \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    --data-binary @/app/data/brands.jsonl
echo ""
curl -sf "$BASE/collections/products/documents/import?action=create" -X POST \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    --data-binary @/app/data/products.jsonl
echo ""
curl -sf "$BASE/collections/reviews/documents/import?action=create" -X POST \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    --data-binary @/app/data/reviews.jsonl
echo ""

# BROKEN synonym: laptop is one-way (root="laptop") — should be multi-way
curl -sf "$BASE/collections/products/synonyms/laptop_synonyms" -X PUT \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"root":"laptop","synonyms":["notebook","portable computer"]}'
echo ""

# BROKEN synonym: mobile/phone/smartphone is multi-way — should be one-way from mobile
curl -sf "$BASE/collections/products/synonyms/mobile_synonym" -X PUT \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"synonyms":["mobile","phone","smartphone"]}'
echo ""

# BROKEN curation: match is "contains" — should be "exact"
curl -sf "$BASE/collections/products/overrides/featured_override" -X PUT \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"rule":{"query":"featured","match":"contains"},"includes":[{"id":"prod_5","position":1}],"excludes":[{"id":"prod_4"}]}'
echo ""

# BROKEN API key: scoped to all collections — should be products only
KEY_RESP=$(curl -sf "$BASE/keys" -X POST \
    -H "Content-Type: application/json" \
    -H "X-TYPESENSE-API-KEY: $API_KEY" \
    -d '{"description":"Search-only key for products","actions":["documents:search"],"collections":["*"]}')
KEY_VALUE=$(echo "$KEY_RESP" | jq -r '.value')
echo "$KEY_VALUE" > /app/search_only_key.txt

echo "Broken setup complete, shutting down..."

kill "$SERVER_PID"
wait "$SERVER_PID" 2>/dev/null || true
sleep 1
echo "Done."
