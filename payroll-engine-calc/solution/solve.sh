#!/usr/bin/env bash

cp /solution/payroll_engine.py /app/payroll_engine.py
cp /solution/Makefile /app/Makefile
cp /solution/payroll_validator.jq /app/payroll_validator.jq
cd /app
make all
