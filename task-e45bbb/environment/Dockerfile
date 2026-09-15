FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-yaml \
    make \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 -q

RUN mkdir -p /app/src /app/map /app/config /app/mission /app/schema

COPY generate_environment.py /tmp/generate_environment.py
RUN python3 /tmp/generate_environment.py && rm /tmp/generate_environment.py

COPY src/ /app/src/
COPY config/ /app/config/
COPY mission/ /app/mission/
COPY schema/ /app/schema/
COPY Makefile /app/Makefile

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3
