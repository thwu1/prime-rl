#!/bin/bash

pip3 install datasketches==5.1.1 -q

cp /solution/kll_impl.py /app/kll_sketch.py
cp /solution/kll_tool.py /app/kll_tool.py
