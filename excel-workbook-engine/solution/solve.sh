#!/bin/bash

pip3 install openpyxl==3.1.5 -q
cd /app
python3 /solution/build_workbook.py
