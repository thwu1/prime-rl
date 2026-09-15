#!/bin/bash

set -e

pip3 install pytest==8.3.4 -q

chmod +x /solution/extract_globals.sh /solution/extract_func.sh
python3 /solution/pkgaudit.py
