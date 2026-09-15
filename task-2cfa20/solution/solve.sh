#!/bin/bash

pip3 install beautifulsoup4==4.12.3 langdetect==1.0.9 -q

cd /app
python3 /solution/auditor.py
