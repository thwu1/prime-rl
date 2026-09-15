
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 gcc make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/reference /app/tools

COPY config.json /app/config.json
COPY allocator.py /app/allocator.py
COPY create_db.py /tmp/create_db.py
RUN python3 /tmp/create_db.py && rm /tmp/create_db.py
COPY reference/architecture.md /app/reference/architecture.md
COPY tools/poolcheck.c /app/tools/poolcheck.c
COPY tools/Makefile /app/tools/Makefile

WORKDIR /app
