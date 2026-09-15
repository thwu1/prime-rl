#!/usr/bin/env bash
#
# Multi-stage HL7v2 validation pipeline:
#   Stage 1: IGAMT model-based validation (Python)
#   Stage 2: Schematron validation (xsltproc + xmlstarlet)
#   Stage 3: Result merging (Python)

PROFILE_DIR="$1"
MSG_FILE="$2"
SCH_XSL="/app/schematron/iso_svrl.xsl"

# Input validation
if [ $# -ne 2 ]; then
    echo '{"valid":false,"errors":[{"category":"PARSE","path":"","message":"Usage: validate.sh <profile_dir> <message_file>"}],"warnings":[]}'
    exit 1
fi

if [ ! -d "$PROFILE_DIR" ]; then
    echo '{"valid":false,"errors":[{"category":"PARSE","path":"","message":"Profile directory not found"}],"warnings":[]}'
    exit 1
fi

if [ ! -f "$MSG_FILE" ]; then
    echo '{"valid":false,"errors":[{"category":"PARSE","path":"","message":"Message file not found"}],"warnings":[]}'
    exit 1
fi

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# ── Stage 1: IGAMT model-based validation ────────────────────────

python3 /app/igamt_validate.py "$PROFILE_DIR" "$MSG_FILE" > "$TMPDIR/igamt.json" 2>/dev/null

if [ ! -s "$TMPDIR/igamt.json" ]; then
    echo '{"valid":false,"errors":[{"category":"PARSE","path":"","message":"IGAMT validation failed"}],"warnings":[]}'
    exit 1
fi

# ── Stage 2: Schematron validation ───────────────────────────────

touch "$TMPDIR/svrl_failures.txt"
SCH_FILE="$PROFILE_DIR/rules.sch"

if [ -f "$SCH_FILE" ] && [ -f "$SCH_XSL" ]; then
    # 2a: Convert ER7 message to XML
    python3 /app/er7_to_xml.py "$MSG_FILE" > "$TMPDIR/message.xml" 2>/dev/null

    if [ $? -eq 0 ] && [ -s "$TMPDIR/message.xml" ]; then
        # 2b: Compile Schematron rules using xsltproc
        xsltproc "$SCH_XSL" "$SCH_FILE" > "$TMPDIR/compiled.xsl" 2>/dev/null

        if [ $? -eq 0 ] && [ -s "$TMPDIR/compiled.xsl" ]; then
            # 2c: Apply compiled Schematron to XML message
            xsltproc "$TMPDIR/compiled.xsl" "$TMPDIR/message.xml" > "$TMPDIR/svrl.xml" 2>/dev/null

            if [ $? -eq 0 ] && [ -s "$TMPDIR/svrl.xml" ]; then
                # 2d: Parse SVRL output with xmlstarlet to extract failed assertions
                xmlstarlet sel \
                    -N svrl="http://purl.oclc.org/dsdl/svrl" \
                    -t -m "//svrl:failed-assert" \
                    -v "concat(@id, '||', normalize-space(svrl:text))" -n \
                    "$TMPDIR/svrl.xml" > "$TMPDIR/svrl_failures.txt" 2>/dev/null || true
            fi
        fi
    fi
fi

# ── Stage 3: Merge results ───────────────────────────────────────

python3 /app/merge_results.py "$TMPDIR/igamt.json" "$TMPDIR/svrl_failures.txt"
exit $?
