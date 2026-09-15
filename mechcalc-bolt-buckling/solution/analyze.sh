#!/usr/bin/env bash

set -euo pipefail

DB="/app/results.db"

init_db() {
    sqlite3 "$DB" "CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, input_file TEXT, timestamp TEXT, report_json TEXT, overall_pass INTEGER);"
}

case "${1:-}" in
    run)
        init_db
        INPUT_FILE="$2"
        CALC_OUTPUT=$(python3 /app/mechcalc.py < "$INPUT_FILE")
        COMBINED=$(jq -n --argjson inp "$(cat "$INPUT_FILE")" --argjson out "$CALC_OUTPUT" '{"input":$inp,"output":$out}')
        REPORT=$(echo "$COMBINED" | jq -f /app/report.jq)
        OVERALL=$(echo "$REPORT" | jq '.overall_pass | if . then 1 else 0 end')
        TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        ESCAPED=$(echo "$REPORT" | sed "s/'/''/g")
        sqlite3 "$DB" "INSERT INTO runs(input_file,timestamp,report_json,overall_pass) VALUES('$(basename "$INPUT_FILE")','$TS','$ESCAPED',$OVERALL);"
        echo "$REPORT"
        ;;
    history)
        init_db
        sqlite3 "$DB" "SELECT json_group_array(json_object('id',id,'input_file',input_file,'timestamp',timestamp,'overall_pass',overall_pass)) FROM (SELECT * FROM runs ORDER BY id DESC);"
        ;;
    compare)
        init_db
        sqlite3 "$DB" "SELECT report_json FROM runs WHERE id=$2;" > /tmp/_cmp_r1.json
        sqlite3 "$DB" "SELECT report_json FROM runs WHERE id=$3;" > /tmp/_cmp_r2.json
        jq -n --slurpfile r1 /tmp/_cmp_r1.json --slurpfile r2 /tmp/_cmp_r2.json '
        ($r1[0]) as $a | ($r2[0]) as $b | {
            modules: [range($a.modules|length) | . as $i | {
                name: $a.modules[$i].name,
                margin_delta: ($b.modules[$i].margin_pct - $a.modules[$i].margin_pct)
            }],
            overall_delta: ($b.min_margin_pct - $a.min_margin_pct)
        }'
        rm -f /tmp/_cmp_r1.json /tmp/_cmp_r2.json
        ;;
    *)
        echo "Usage: analyze.sh {run|history|compare}" >&2
        exit 1
        ;;
esac
