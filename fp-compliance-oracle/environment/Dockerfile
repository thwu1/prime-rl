FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y gcc make python3-pip && \
    rm -rf /var/lib/apt/lists/*


COPY fp_oracle.h /app/fp_oracle.h
COPY fp_oracle.c /app/fp_oracle.c
COPY main.c /app/main.c
COPY Makefile /app/Makefile

WORKDIR /app
