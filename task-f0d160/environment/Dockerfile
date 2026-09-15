
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY roofline_core.c Makefile roofline.py /app/
COPY scenarios.json analysis.json reference.json output_schema.json /app/data/
COPY create_db.sql /tmp/create_db.sql
RUN sqlite3 /app/data/hardware.db < /tmp/create_db.sql && rm /tmp/create_db.sql
RUN cd /app && make

WORKDIR /app
