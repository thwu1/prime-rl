#!/bin/bash


mkdir -p /app/xsl
cp /solution/nominal.xsl /app/xsl/nominal.xsl
cp /solution/real.xsl /app/xsl/real.xsl
cp /solution/schema.sql /app/schema.sql
cp /solution/Makefile /app/Makefile
cp /solution/tips_analytics.py /app/tips_analytics.py

cd /app && make db
