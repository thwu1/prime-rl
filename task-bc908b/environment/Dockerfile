FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install flask==2.3.3 werkzeug==2.3.7 schemathesis==3.19.0 hypothesis==6.82.0

COPY api/ /app/api/
COPY spec/ /app/spec/
COPY start_server.py /app/start_server.py

RUN python3 -m compileall -b /app/api/ && rm /app/api/server.py

RUN mkdir -p /app/results

WORKDIR /app
