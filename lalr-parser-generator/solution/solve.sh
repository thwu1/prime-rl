#!/bin/bash

cp /solution/lalr_gen.py /app/lalr_gen
chmod +x /app/lalr_gen
cp /solution/Makefile /app/Makefile
cd /app && make all
