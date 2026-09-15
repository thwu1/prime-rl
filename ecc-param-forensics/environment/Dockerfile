FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS generator
RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*
COPY generate_challenges.py /tmp/gen.py
RUN python3 /tmp/gen.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    libssl-dev \
    openssl \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=generator /app/data /app/data
COPY monty_check.c /app/tools/monty_check.c
RUN mkdir -p /app/results
WORKDIR /app
