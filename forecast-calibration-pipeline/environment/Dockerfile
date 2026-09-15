FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data /app/output

COPY data/config.yaml /data/config.yaml
COPY data/INSTR_A.csv /data/INSTR_A.csv
COPY data/INSTR_B.csv /data/INSTR_B.csv
COPY data/INSTR_C.csv /data/INSTR_C.csv
COPY data/INSTR_D.csv /data/INSTR_D.csv

WORKDIR /app
