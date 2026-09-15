FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    make \
    && rm -rf /var/lib/apt/lists/*

COPY problem.md /app/problem.md
COPY scorer.py /app/scorer.py
COPY benchmark.py /app/benchmark.py
COPY Makefile /app/Makefile
COPY run_solver.sh /app/run_solver.sh
COPY generate_cases.py /tmp/generate_cases.py

RUN python3 /tmp/generate_cases.py && rm /tmp/generate_cases.py
RUN chmod +x /app/run_solver.sh

WORKDIR /app
