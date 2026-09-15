#!/bin/bash

cp /solution/nft_audit.py /app/nft_audit.py

mkdir -p /app/results
python3 /app/nft_audit.py /app/configs/workstation.conf /app/queries.json /app/results/workstation.json
python3 /app/nft_audit.py /app/configs/server.conf /app/queries.json /app/results/server.json
python3 /app/nft_audit.py /app/configs/router.conf /app/queries.json /app/results/router.json
