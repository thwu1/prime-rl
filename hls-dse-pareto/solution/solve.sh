#!/bin/bash

pip3 install pyyaml==6.0.2 -q

cp /solution/dse_tool.py /app/dse_tool.py
cp /solution/Makefile /app/Makefile
cd /app
make all
