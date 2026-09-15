FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y gcc python3 python3-pip xxd && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/databases /app/tools

COPY FORMAT.md /app/FORMAT.md
COPY pgverify.c /app/tools/pgverify.c
COPY generate_dbs.py /tmp/generate_dbs.py

RUN python3 /tmp/generate_dbs.py && rm /tmp/generate_dbs.py

WORKDIR /app
