
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip curl jq sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/test_vectors

COPY cpu6502.py /app/cpu6502.py
COPY cpu6502.py /app/cpu6502_original.py
COPY run_tests.py /app/run_tests.py
COPY test_vectors/ /app/test_vectors/

WORKDIR /app
