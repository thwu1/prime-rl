#!/usr/bin/env bash

pip3 install requests==2.32.3 -q

cp /solution/analyze.py /app/analyze.py
chmod +x /app/analyze.py
