#!/bin/bash

# The solution reverse engineers the vault_tool binary's encryption algorithms
# using radare2 disassembly and implements a general-purpose vault parser.
# No additional pip deps needed — uses only stdlib (struct, zlib, hashlib, json).

cp /solution/parser.py /app/vault_parser.py
python3 /app/vault_parser.py /app/archive.vault /app/results
python3 /app/vault_parser.py /app/test_extra.vault /app/results_extra
