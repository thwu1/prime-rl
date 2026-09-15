FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip gcc make && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
WORKDIR /app

COPY reference_data.json /app/reference_data.json
COPY qcm_transfer.c /app/qcm_transfer.c
COPY Makefile /app/Makefile
COPY qcm_analysis.py /app/qcm_analysis.py
