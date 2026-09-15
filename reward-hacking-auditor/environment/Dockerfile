
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    diffutils \
    jq \
    file \
    yara \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY setup_runs.py /tmp/setup_runs.py
RUN python3 /tmp/setup_runs.py && rm /tmp/setup_runs.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
