#!/bin/bash

# Install solution dependencies
pip3 install pandas==2.2.3 pyreadstat==1.2.7 lxml==5.3.0 -q

cd /app
python3 /solution/sdtm_builder.py
