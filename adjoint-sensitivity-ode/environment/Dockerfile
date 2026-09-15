FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY system.py /app/system.py
COPY observations.csv /app/data/observations.csv
COPY metadata.toml /app/data/metadata.toml
COPY config.toml /app/config.toml
COPY driver.py /app/driver.py
COPY run_pipeline.sh /app/run_pipeline.sh
RUN chmod +x /app/run_pipeline.sh

WORKDIR /app
