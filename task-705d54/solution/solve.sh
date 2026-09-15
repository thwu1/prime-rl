#!/bin/bash

# Fix bugs in views.sql, checker.py, and postprocess.sh,
# then implement missing rules 9-14 with effective method computation.
cp /solution/fix_views.sql /app/views.sql
cp /solution/fix_checker.py /app/checker.py
cp /solution/fix_postprocess.sh /app/postprocess.sh

cd /app && make clean && make check
