#!/bin/bash

pip3 install laspy==2.5.4 numpy==2.1.3 -q

cd /app
python3 /solution/validator.py
