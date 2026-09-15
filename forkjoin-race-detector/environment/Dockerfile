FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip graphviz make jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/programs /app/results /app/graphs

COPY spec.md /app/spec.md
COPY Makefile /app/Makefile
COPY analyzer_stub.py /app/analyzer_stub.py
COPY programs/simple_fork_join.json /app/programs/simple_fork_join.json
COPY programs/nested_finish.json /app/programs/nested_finish.json
COPY programs/diamond_pattern.json /app/programs/diamond_pattern.json
COPY programs/phaser_sync.json /app/programs/phaser_sync.json
COPY programs/multi_phase.json /app/programs/multi_phase.json

WORKDIR /app
