FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip redis-server && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install redis==5.0.3

RUN mkdir -p /app/tools /app/setup

COPY profiler.py /app/tools/profiler.py
COPY load_data.py /app/setup/load_data.py
COPY notes.md /app/NOTES.md

WORKDIR /app
