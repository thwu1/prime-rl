FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/native

COPY native/cost_model_gen.c /app/native/cost_model_gen.c
COPY native/Makefile /app/native/Makefile

COPY gen_hw_spec.py /tmp/gen_hw_spec.py
RUN python3 /tmp/gen_hw_spec.py && rm /tmp/gen_hw_spec.py

COPY init_db.sql /tmp/init_db.sql
RUN sqlite3 /app/cluster.db < /tmp/init_db.sql && rm /tmp/init_db.sql

COPY topology.json /app/topology.json
COPY lib.py /app/lib.py
COPY strategies.py /app/strategies.py

WORKDIR /app
