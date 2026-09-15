
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY specs.md /app/specs.md
COPY replay_tool.py /app/replay-tool
COPY setup_db.py /app/setup_db.py
COPY generate_example.py /app/generate_example.py

RUN chmod +x /app/replay-tool
RUN ln -s /app/replay-tool /usr/local/bin/replay-tool
RUN python3 /app/setup_db.py
RUN python3 /app/generate_example.py && rm /app/generate_example.py /app/setup_db.py

RUN mkdir -p /app/replays /app/results
