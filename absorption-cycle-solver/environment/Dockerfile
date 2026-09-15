FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/data

COPY nh3h2o_draft.py /app/nh3h2o_draft.py
COPY data/correlations.json /app/data/correlations.json
COPY data/cycle_config.json /app/data/cycle_config.json
COPY data/benchmark.csv /app/data/benchmark.csv

WORKDIR /app
