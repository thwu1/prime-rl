#!/bin/bash
# Validate prediction files against NIST submission format
# Usage: validate.sh <db_path> <data_dir> <output_dir>

DB="$1"
DATA_DIR="$2"
OUT_DIR="$3"

if [ -z "$DB" ] || [ -z "$DATA_DIR" ] || [ -z "$OUT_DIR" ]; then
    echo "Usage: validate.sh <db_path> <data_dir> <output_dir>" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

echo "{" > "$OUT_DIR/validation_report.json"
first=true

for pred_file in "$DATA_DIR"/predictions/*.json; do
    stem=$(basename "$pred_file" .json)

    errors=()

    # Check required top-level fields
    for field in team docker_id input prediction_list execution_time; do
        if ! jq -e "has(\"$field\")" "$pred_file" > /dev/null 2>&1; then
            errors+=("Missing required field: $field")
        fi
    done

    # Check individual prediction entries
    entry_count=$(jq '.prediction_list | length' "$pred_file" 2>/dev/null || echo 0)

    for ((i=0; i<entry_count; i++)); do
        # Check required prediction fields
        for field in statement_id ai_likelihood_score believability_score; do
            has_field=$(jq -r ".prediction_list[$i] | has(\"$field\")" "$pred_file" 2>/dev/null)
            if [ "$has_field" != "true" ]; then
                errors+=("Entry $i: missing field $field")
            fi
        done

        # Check ai_likelihood_score range [0, 1]
        score=$(jq -r ".prediction_list[$i].ai_likelihood_score // empty" "$pred_file" 2>/dev/null)
        if [ -n "$score" ]; then
            in_range=$(echo "$score" | awk '{print ($1 >= 0 && $1 <= 1) ? "yes" : "no"}')
            if [ "$in_range" = "no" ]; then
                errors+=("Entry $i: ai_likelihood_score $score out of range [0,1]")
            fi
        fi

        # Check believability_score range [0, 1]
        bscore=$(jq -r ".prediction_list[$i].believability // empty" "$pred_file" 2>/dev/null)
        if [ -n "$bscore" ]; then
            bel_valid=$(echo "$bscore" | awk '{print ($1 >= 0 && $1 <= 1) ? "yes" : "no"}')
            if [ "$bel_valid" = "no" ]; then
                errors+=("Entry $i: believability_score $bscore out of range [0,1]")
            fi
        fi
    done

    # Build JSON error array
    error_json="["
    for ((j=0; j<${#errors[@]}; j++)); do
        if [ $j -gt 0 ]; then error_json+=","; fi
        error_json+="\"${errors[$j]}\""
    done
    error_json+="]"

    valid="true"
    if [ ${#errors[@]} -gt 0 ]; then
        valid="false"
        sqlite3 "$DB" "UPDATE submissions SET is_valid=0, validation_errors='$error_json' WHERE file_stem='$stem';"
    fi

    if [ "$first" = true ]; then
        first=false
    else
        echo "," >> "$OUT_DIR/validation_report.json"
    fi

    echo "  \"$stem\": {\"valid\": $valid, \"errors\": $error_json}" >> "$OUT_DIR/validation_report.json"
done

echo "}" >> "$OUT_DIR/validation_report.json"
echo "Validation complete"
