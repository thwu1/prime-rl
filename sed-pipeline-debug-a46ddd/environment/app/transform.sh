#!/bin/bash
#
# Text processing pipeline using GNU sed
# Phase 1: join continuation lines
# Phase 2: fold tagged entries
# Phase 3: remove consecutive duplicates
# Phase 4: number each line with [NNN] prefix

sed -f /app/join.sed "$@" | sed -f /app/fold.sed | sed -f /app/dedup.sed | sed -f /app/number.sed
