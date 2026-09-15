FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip gcc make libc6-dev \
    && rm -rf /var/lib/apt/lists/*


COPY cubic_core.c /app/cubic_core.c
COPY Makefile /app/Makefile
COPY eos_engine.py /app/eos_engine.py
COPY params.toml /app/params.toml

WORKDIR /app
