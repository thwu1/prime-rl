FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    graphviz \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

COPY data/dependencies.dot /app/data/dependencies.dot
COPY data/governance.yaml /app/data/governance.yaml
COPY data/components.sql /tmp/components.sql

RUN mkdir -p /app/data && sqlite3 /app/data/components.db < /tmp/components.sql && rm /tmp/components.sql

COPY pipeline/ /app/pipeline/
RUN chmod +x /app/pipeline/run.sh

RUN mkdir -p /app/results

WORKDIR /app
