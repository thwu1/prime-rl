
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip graphviz && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/analysis /app/results

COPY equations.p /app/analysis/equations.p
COPY claimed_implications.csv /app/analysis/claimed_implications.csv
COPY notes.txt /app/analysis/notes.txt

WORKDIR /app
