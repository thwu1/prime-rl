FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip gcc make sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY gpu_config.json /app/gpu_config.json
COPY kernels.json /app/kernels.json
COPY sim.py /app/sim.py
COPY validate.sh /app/validate.sh
COPY bankmap.c /app/bankmap.c
COPY Makefile /app/Makefile
COPY spec.md /app/spec.md
COPY strategies.json /app/strategies.json
COPY init_db.sql /tmp/init_db.sql

RUN sqlite3 /app/profiling.db < /tmp/init_db.sql && rm /tmp/init_db.sql

RUN chmod +x /app/validate.sh /app/sim.py

WORKDIR /app
