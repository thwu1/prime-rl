#!/bin/bash

set -e

mkdir -p /app/hgvs_parser
cp /solution/hgvs_impl.py /app/hgvs_parser/__init__.py
cp /solution/hgvs_cli.py /app/hgvs-tool
chmod +x /app/hgvs-tool
cp /solution/Makefile /app/Makefile

echo "HGVS parser package, CLI tool, and Makefile installed at /app/"
