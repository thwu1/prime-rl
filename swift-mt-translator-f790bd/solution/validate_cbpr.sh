#!/bin/bash

# CBPR+ Validation Pipeline
# Uses xmlstarlet for XPath extraction and jq for JSON assembly

XML_FILE="$1"

if [ -z "$XML_FILE" ] || [ ! -f "$XML_FILE" ]; then
    echo '{"valid":false,"checks":[]}' | jq .
    exit 1
fi

CHECKS='[]'
ALL_PASS=true

add_check() {
    local name="$1"
    local pass="$2"
    local value="$3"
    CHECKS=$(echo "$CHECKS" | jq --arg n "$name" --argjson p "$pass" --arg v "$value" \
        '. + [{"name":$n,"pass":$p,"value":$v}]')
    if [ "$pass" = "false" ]; then
        ALL_PASS=false
    fi
}

# Check BizSvc
BIZSVC=$(xmlstarlet sel -t -v "//*[local-name()='BizSvc']" "$XML_FILE" 2>/dev/null || echo "")
if [ "$BIZSVC" = "swift.cbprplus.02" ]; then
    add_check "bizsvc" true "$BIZSVC"
else
    add_check "bizsvc" false "$BIZSVC"
fi

# Check MsgDefIdr
MSGDEF=$(xmlstarlet sel -t -v "//*[local-name()='MsgDefIdr']" "$XML_FILE" 2>/dev/null || echo "")
if [ "$MSGDEF" = "pacs.008.001.08" ]; then
    add_check "msg_def_idr" true "$MSGDEF"
else
    add_check "msg_def_idr" false "$MSGDEF"
fi

# Check NbOfTxs
NBTXS=$(xmlstarlet sel -t -v "//*[local-name()='NbOfTxs']" "$XML_FILE" 2>/dev/null || echo "")
if [ "$NBTXS" = "1" ]; then
    add_check "nb_of_txs" true "$NBTXS"
else
    add_check "nb_of_txs" false "$NBTXS"
fi

# Check UETR present
UETR=$(xmlstarlet sel -t -v "//*[local-name()='UETR']" "$XML_FILE" 2>/dev/null || echo "")
if [ -n "$UETR" ]; then
    add_check "uetr_present" true "$UETR"
else
    add_check "uetr_present" false ""
fi

# Check EndToEndId present
E2E=$(xmlstarlet sel -t -v "//*[local-name()='EndToEndId']" "$XML_FILE" 2>/dev/null || echo "")
if [ -n "$E2E" ]; then
    add_check "e2e_id_present" true "$E2E"
else
    add_check "e2e_id_present" false ""
fi

# Check all BICFI are 11 chars
BIC_PASS=true
BAD_BIC=""
BICFIS=$(xmlstarlet sel -t -m "//*[local-name()='BICFI']" -v "." -n "$XML_FILE" 2>/dev/null || echo "")
while IFS= read -r BIC; do
    [ -z "$BIC" ] && continue
    if [ ${#BIC} -ne 11 ]; then
        BIC_PASS=false
        BAD_BIC="$BIC"
        break
    fi
done <<< "$BICFIS"
if [ "$BIC_PASS" = true ]; then
    add_check "bicfi_11_chars" true ""
else
    add_check "bicfi_11_chars" false "$BAD_BIC"
fi

# Check all AnyBIC are 11 chars
ABIC_PASS=true
BAD_ABIC=""
HAS_ANYBIC=false
ANYBICS=$(xmlstarlet sel -t -m "//*[local-name()='AnyBIC']" -v "." -n "$XML_FILE" 2>/dev/null || echo "")
while IFS= read -r BIC; do
    [ -z "$BIC" ] && continue
    HAS_ANYBIC=true
    if [ ${#BIC} -ne 11 ]; then
        ABIC_PASS=false
        BAD_ABIC="$BIC"
        break
    fi
done <<< "$ANYBICS"
if [ "$HAS_ANYBIC" = true ]; then
    if [ "$ABIC_PASS" = true ]; then
        add_check "anybic_11_chars" true ""
    else
        add_check "anybic_11_chars" false "$BAD_ABIC"
    fi
fi

# Final JSON output via jq
if [ "$ALL_PASS" = true ]; then
    echo "$CHECKS" | jq '{"valid":true,"checks":.}'
    exit 0
else
    echo "$CHECKS" | jq '{"valid":false,"checks":.}'
    exit 1
fi
