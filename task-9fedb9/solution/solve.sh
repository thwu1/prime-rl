#!/usr/bin/env bash

set -euo pipefail

# No additional pip dependencies needed — solution uses only Python stdlib
# (ipaddress, json, csv, os, pathlib, collections, re)

python3 /solution/auditor.py
