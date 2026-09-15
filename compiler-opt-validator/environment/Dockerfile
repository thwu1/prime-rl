
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
        python3-pip \
        gcc \
        clang \
        build-essential \
        binutils \
    && rm -rf /var/lib/apt/lists/*

COPY app_scaffold/ /app/

RUN mkdir -p /app/tests/volatile_opt \
             /app/tests/int_promo \
             /app/tests/call_conv

RUN chmod +x /app/runner.py /app/report.py

WORKDIR /app
