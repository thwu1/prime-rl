#!/bin/bash

cd /app

# Decode the postcard-RPC capture using FNV1a-64 key derivation,
# bidirectional COBS/postcard encoding, invalid frame forensics,
# nested EventKind enum handling, and cross-message thermal correlation.
python3 /solution/decoder.py
