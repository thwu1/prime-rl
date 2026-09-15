
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip gcc make && rm -rf /var/lib/apt/lists/*

COPY machine.py /app/machine.py
COPY programs.py /app/programs.py
COPY optimizer_stub.py /app/optimizer.py
COPY bundle_check.c /app/bundle_check.c
COPY machine.spec /app/machine.spec
COPY Makefile /app/Makefile

WORKDIR /app
