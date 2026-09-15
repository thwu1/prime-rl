FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/data

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY benchmark_buggy.py /app/benchmark.py
COPY readme_app.md /app/README.md

WORKDIR /app
