#!/bin/bash

GRAMMAR=""
CORPUS=""
ITERATIONS=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --grammar) GRAMMAR="$2"; shift 2;;
        --corpus) CORPUS="$2"; shift 2;;
        --iterations) ITERATIONS="$2"; shift 2;;
        *) shift;;
    esac
done

# Run core algorithm: outputs JSON to stdout, creates SQLite DB, writes DOT files
python3 /app/pcfg_core.py \
    --grammar "$GRAMMAR" \
    --corpus "$CORPUS" \
    --iterations "$ITERATIONS" \
    --db /app/grammar.db \
    --treedir /app/trees

# Render parse tree DOT files to SVG using graphviz
for dotfile in /app/trees/sentence_*.dot; do
    [ -f "$dotfile" ] || continue
    svgfile="${dotfile%.dot}.svg"
    dot -Tsvg "$dotfile" -o "$svgfile"
done
