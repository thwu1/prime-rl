#!/bin/bash

pip3 install numpy==2.1.3 -q

cd /app
make

cp /solution/optimizer_impl.py /app/optimizer.py
