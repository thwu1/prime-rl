FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc make sqlite3 \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/src /app/legacy /app/reference /app/configs

COPY src/balance_core.h /app/src/balance_core.h
COPY src/balance_core.c /app/src/balance_core.c
COPY Makefile /app/Makefile
COPY legacy/balance_tool.py /app/legacy/balance_tool.py
COPY legacy/README.md /app/legacy/README.md
COPY reference/theory.txt /app/reference/theory.txt
COPY reference/worked_examples.txt /app/reference/worked_examples.txt
COPY configs/sample_rotating.toml /app/configs/sample_rotating.toml
COPY configs/sample_reciprocating.toml /app/configs/sample_reciprocating.toml
COPY configs/sample_flywheel.toml /app/configs/sample_flywheel.toml

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
