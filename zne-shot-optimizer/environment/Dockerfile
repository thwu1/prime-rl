FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip sqlite3 jq make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY noise_model.py /app/noise_model.py
COPY extrapolators.py /app/extrapolators.py
COPY allocator.py /app/allocator.py
COPY benchmark.py /app/benchmark.py
COPY create_db.py /app/create_db.py
COPY extract_scenarios.sql /app/extract_scenarios.sql
COPY postprocess.jq /app/postprocess.jq
COPY Makefile /app/Makefile
COPY zne_optimizer.py /app/zne_optimizer.py
COPY run_analysis.py /app/run_analysis.py
COPY problems.json /app/problems.json

RUN python3 /app/create_db.py && rm /app/create_db.py

WORKDIR /app
