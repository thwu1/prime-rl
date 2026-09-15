#!/bin/bash

cd /app

cp /solution/decoder.py /app/decode_adsb.py
python3 /app/decode_adsb.py
