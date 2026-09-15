#!/bin/bash

pip3 install lxml==5.3.1 -q

cd /app
python3 /solution/repair_network.py
