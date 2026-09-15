FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip build-essential && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY hx_rate.py /app/hx_rate.py
COPY bell_delaware.py /app/bell_delaware.py
COPY libcorr.c /app/libcorr.c
COPY Makefile /app/Makefile
COPY coefficients.csv /app/coefficients.csv
COPY case1.json /app/case1.json
COPY case2.json /app/case2.json
COPY case3.json /app/case3.json
COPY case4.json /app/case4.json

WORKDIR /app
