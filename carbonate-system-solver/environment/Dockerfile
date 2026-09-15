FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        octave \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/cruise_data

COPY carbonate_solver.py /app/carbonate_solver.py
COPY validate_constants.m /app/validate_constants.m
COPY crossover_spec.json /app/crossover_spec.json
COPY cruise_data/ /app/cruise_data/

