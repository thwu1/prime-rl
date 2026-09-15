#!/bin/bash

pip3 install sqlglot==26.31.1 -q

cp /solution/decomposer_impl.py /app/decomposer.py

cd /app
python3 -c "from decomposer import decompose_query; print('decomposer module loaded successfully')"
