FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY measurements.csv /app/measurements.csv
COPY si_nk.csv /app/si_nk.csv
COPY stack_config.json /app/stack_config.json
COPY tmm_solver.py /app/tmm_solver.py

WORKDIR /app
