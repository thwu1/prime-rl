FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-numpy \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY problem_spec.py /app/problem_spec.py
COPY generate_data.py /app/generate_data.py
COPY coeffgen.c /app/coeffgen.c

RUN python3 /app/generate_data.py

WORKDIR /app
