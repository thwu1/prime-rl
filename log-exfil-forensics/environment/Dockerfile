FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder


RUN apt-get update && apt-get install -y openssl python3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/logs

COPY generate_logs.py /tmp/generate_logs.py
RUN python3 /tmp/generate_logs.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/logs /app/logs
COPY candidate_rules.json /app/candidate_rules.json
