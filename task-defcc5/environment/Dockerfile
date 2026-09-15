FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY spec.md /app/spec.md
COPY prism_gravity.py /app/prism_gravity.py
COPY reference_cases.json /app/reference_cases.json

WORKDIR /app
