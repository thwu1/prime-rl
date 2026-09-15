FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq sqlite3 make && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY docs/ /app/docs/
COPY replays/ /app/replays/
COPY engine_buggy.py /app/engine.py
COPY Makefile /app/Makefile
COPY tools/ /app/tools/
COPY filters/ /app/filters/

# Build reference database and NDJSON event logs from replay traces
COPY build_reference.py /tmp/build_reference.py
RUN python3 /tmp/build_reference.py && rm /tmp/build_reference.py
