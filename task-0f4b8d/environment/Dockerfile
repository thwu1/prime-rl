FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tools

COPY grid.txt /app/grid.txt
COPY tools/ua_finder.c /app/tools/ua_finder.c
COPY tools/Makefile /app/tools/Makefile
COPY tools/clique_finder.py /app/tools/clique_finder.py
COPY tools/README.txt /app/tools/README.txt
COPY pipeline.log /app/pipeline.log
COPY setup_db.py /tmp/setup_db.py

RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
