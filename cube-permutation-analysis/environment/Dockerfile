
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN sed -i 's/Components: main/Components: main universe/' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true

RUN apt-get update && \
    apt-get install -y python3 python3-pip gap-core sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY scrambles.txt /app/scrambles.txt
COPY cube_sim.py /app/cube_sim.py

WORKDIR /app
