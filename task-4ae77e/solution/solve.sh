#!/bin/bash

pip3 install numpy==1.26.4 scipy==1.13.1 nlopt==2.7.1 -q
cp /solution/cantilever_driver.py /app/cantilever_driver.py
chmod +x /app/cantilever_driver.py
python3 /solution/solve.py
