FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm -f /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 graphviz && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app /app
WORKDIR /app
