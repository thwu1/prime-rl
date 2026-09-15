#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/elliptic_filter_impl.py /app/elliptic_filter.py

cd /app
python3 tools/filterspec.py pipeline --configs reference_data/ --output output/
