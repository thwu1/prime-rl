FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY init_kvs_store.py /tmp/init_kvs_store.py
RUN python3 /tmp/init_kvs_store.py && rm /tmp/init_kvs_store.py

COPY docs/ /app/docs/

RUN mkdir -p /app/output

WORKDIR /app
