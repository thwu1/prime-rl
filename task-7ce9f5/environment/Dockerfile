FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    libxml2-utils \
    gzip \
    && rm -rf /var/lib/apt/lists/*

COPY graph_gen.py /tmp/graph_gen.py
RUN python3 /tmp/graph_gen.py && rm /tmp/graph_gen.py && \
    test -f /opt/graphdata/network.db && \
    test -f /opt/graphdata/adjacency_secondary.mtx && \
    test -f /opt/graphdata/supplement.graphml && \
    test -f /opt/graphdata/corrections.edges.gz

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
