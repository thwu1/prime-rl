#!/bin/bash

cd /app
python3 /solution/patch_server.py
make clean && make
