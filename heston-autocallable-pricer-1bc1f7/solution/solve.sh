#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cp /solution/pricer.py /app/pricer.py
cp /solution/pipeline.mk /app/Makefile
chmod +x /app/pricer.py
