#!/bin/bash

# Solution uses only Python stdlib (zlib, base64, json, os, re, sqlite3, subprocess)
# plus openssl CLI for vault decryption. No pip dependencies required.

cd /app
python3 /solution/scanner.py
