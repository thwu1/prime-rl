#!/bin/bash

pip3 install numpy==2.1.3 -q
cp /solution/cifcheck.py /app/cifcheck.py
cp /solution/cifbatch.sh /app/cifbatch.sh
chmod +x /app/cifcheck.py /app/cifbatch.sh
