#!/bin/bash
#
# Legacy scoring pipeline v2 — shell-based implementation
# Uses sqlite3 recursive CTEs + jq for JSON formatting
#
# Usage:
#   bash /app/legacy/pipeline.sh scores RUBRIC GRADING
#   bash /app/legacy/pipeline.sh sensitivity RUBRIC
#   bash /app/legacy/pipeline.sh categories RUBRIC GRADING

DB="/app/data/rubrics.db"

cmd_scores() {
    local RUBRIC="$1" GRADING="$2"
    sqlite3 "$DB" "
        WITH RECURSIVE
        sibling_sums AS (
            SELECT parent_id, SUM(weight) as total_w
            FROM rubric_nodes WHERE rubric_name = '${RUBRIC}'
            GROUP BY parent_id
        ),
        ew(node_id, effective_weight, task_category) AS (
            SELECT node_id, 1.0, task_category
            FROM rubric_nodes
            WHERE rubric_name = '${RUBRIC}' AND parent_id IS NULL
            UNION ALL
            SELECT r.node_id,
                   ew.effective_weight * r.weight / ss.total_w,
                   r.task_category
            FROM rubric_nodes r
            JOIN ew ON r.parent_id = ew.node_id
            JOIN sibling_sums ss ON ss.parent_id = ew.node_id
            WHERE r.rubric_name = '${RUBRIC}'
        )
        SELECT ROUND(SUM(ew.effective_weight * COALESCE(g.score, 0)), 6)
        FROM ew
        LEFT JOIN gradings g ON g.node_id = ew.node_id
            AND g.grading_id = '${GRADING}'
        WHERE ew.task_category IS NOT NULL;
    "
}

cmd_sensitivity() {
    local RUBRIC="$1"
    sqlite3 -json "$DB" "
        WITH RECURSIVE
        sibling_sums AS (
            SELECT parent_id, SUM(weight) as total_w
            FROM rubric_nodes WHERE rubric_name = '${RUBRIC}'
            GROUP BY parent_id
        ),
        ew(node_id, effective_weight, task_category) AS (
            SELECT node_id, 1.0, task_category
            FROM rubric_nodes
            WHERE rubric_name = '${RUBRIC}' AND parent_id IS NULL
            UNION ALL
            SELECT r.node_id,
                   ew.effective_weight * r.weight / ss.total_w,
                   r.task_category
            FROM rubric_nodes r
            JOIN ew ON r.parent_id = ew.node_id
            JOIN sibling_sums ss ON ss.parent_id = ew.node_id
            WHERE r.rubric_name = '${RUBRIC}'
        )
        SELECT node_id, ROUND(effective_weight, 6) as ew
        FROM ew WHERE task_category IS NOT NULL
        ORDER BY effective_weight DESC, node_id ASC;
    " | jq '[.[] | {key: .node_id, value: (.ew | tostring | tonumber)}] | sort_by(.key) | [.[] | {(.key): .value}] | add'
}

cmd_categories() {
    local RUBRIC="$1" GRADING="$2"
    sqlite3 -json "$DB" "
        WITH RECURSIVE
        sibling_sums AS (
            SELECT parent_id, SUM(weight) as total_w
            FROM rubric_nodes WHERE rubric_name = '${RUBRIC}'
            GROUP BY parent_id
        ),
        ew(node_id, effective_weight, task_category) AS (
            SELECT node_id, 1.0, task_category
            FROM rubric_nodes
            WHERE rubric_name = '${RUBRIC}' AND parent_id IS NULL
            UNION ALL
            SELECT r.node_id,
                   ew.effective_weight * r.weight / ss.total_w,
                   r.task_category
            FROM rubric_nodes r
            JOIN ew ON r.parent_id = ew.node_id
            JOIN sibling_sums ss ON ss.parent_id = ew.node_id
            WHERE r.rubric_name = '${RUBRIC}'
        ),
        cat_data AS (
            SELECT e.task_category as cat,
                   SUM(e.effective_weight * COALESCE(g.score, 0)) as ws,
                   SUM(e.effective_weight) as tw
            FROM ew e
            LEFT JOIN gradings g ON g.node_id = e.node_id
                AND g.grading_id = '${GRADING}'
            WHERE e.task_category IS NOT NULL
            GROUP BY e.task_category
        )
        SELECT cat, ROUND(ws / tw, 6) as cat_score FROM cat_data ORDER BY cat;
    " | jq '[.[] | {(.cat): (.cat_score | tostring | tonumber)}] | add'
}

case "$1" in
    scores)
        cmd_scores "$2" "$3"
        ;;
    sensitivity)
        cmd_sensitivity "$2"
        ;;
    categories)
        cmd_categories "$2" "$3"
        ;;
    *)
        echo "Usage: $0 {scores|sensitivity|categories} RUBRIC [GRADING]"
        echo ""
        echo "Commands:"
        echo "  scores RUBRIC GRADING     - Compute root-level aggregate score"
        echo "  sensitivity RUBRIC        - Compute leaf effective weights"
        echo "  categories RUBRIC GRADING - Compute per-category scores"
        ;;
esac
