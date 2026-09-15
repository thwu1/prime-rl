FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip jq sqlite3 && rm -rf /var/lib/apt/lists/*

COPY mechanics_reference.md /app/mechanics_reference.md
COPY engine.py /app/engine.py
COPY replays /app/replays
COPY scenarios /app/scenarios

WORKDIR /app
