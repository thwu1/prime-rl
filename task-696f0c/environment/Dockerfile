FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    python3 \
    python3-pip \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/instances /app/results

COPY graph_a.edgelist /app/instances/graph_a.edgelist
COPY graph_b.edgelist /app/instances/graph_b.edgelist
COPY graph_c.edgelist /app/instances/graph_c.edgelist

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4

# drat-trim for independent proof verification (tests/test.sh used to fetch it at run time)
RUN wget -q https://raw.githubusercontent.com/marijnheule/drat-trim/master/drat-trim.c -O /tmp/drat-trim.c && gcc -O2 -o /usr/local/bin/drat-trim /tmp/drat-trim.c && rm /tmp/drat-trim.c
