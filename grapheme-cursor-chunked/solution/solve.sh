#!/usr/bin/env bash

set -euo pipefail

# 1. Download missing emoji data file (correct URL includes emoji/ subdirectory)
curl -fsSL -o /app/data/emoji-data.txt \
    https://www.unicode.org/Public/17.0.0/ucd/emoji/emoji-data.txt

# 2. Fix tables.py: restore InCB_Consonant lookup in grapheme_category()
python3 /solution/fix_tables.py

# 3. Deploy segmenter implementation
cp /solution/grapheme_impl.py /app/segmenter/grapheme.py

echo "Solution deployed."
