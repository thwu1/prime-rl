FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/policies /app/clusterwide-policies /app/cilium-source

COPY init_db.py /tmp/init_db.py
RUN python3 /tmp/init_db.py && rm /tmp/init_db.py

COPY policies/ /app/policies/
COPY clusterwide-policies/ /app/clusterwide-policies/
COPY cilium-source/ /app/cilium-source/
COPY flows.json /app/flows.json
COPY semantics.md /app/semantics.md

WORKDIR /app
