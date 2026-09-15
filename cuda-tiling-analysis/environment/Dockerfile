FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY kernel_warptiling.cuh /app/kernel_warptiling.cuh
COPY runner_constraints.cu /app/runner_constraints.cu
COPY param_ranges.csv /app/param_ranges.csv
COPY problem_spec.json /app/problem_spec.json
COPY team_analysis.json /app/team_analysis.json
COPY create_db.py /tmp/create_db.py
RUN python3 /tmp/create_db.py /app/gpu_specs.db && rm /tmp/create_db.py

WORKDIR /app
