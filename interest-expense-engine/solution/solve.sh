#!/bin/bash

cp /solution/solve_163j.py /app/compute163j.py
cp /solution/Makefile /app/Makefile
cp /solution/gen_report.sh /app/gen_report.sh
chmod +x /app/gen_report.sh
make -C /app all
make -C /app report
