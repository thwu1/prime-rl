
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    graphviz \
    jq \
    make \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/traces /app/graphs /app/schedules

COPY setup/spec.md /app/spec.md
COPY setup/trace1.json /app/traces/trace1.json
COPY setup/trace2.json /app/traces/trace2.json
COPY setup/trace3.json /app/traces/trace3.json
COPY setup/trace4.json /app/traces/trace4.json
COPY setup/trace5.json /app/traces/trace5.json
COPY setup/trace6.json /app/traces/trace6.json

WORKDIR /app
