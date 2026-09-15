FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/
COPY magma/ /app/magma/
COPY Makefile /app/Makefile
COPY audit_report.md /app/audit_report.md

WORKDIR /app
