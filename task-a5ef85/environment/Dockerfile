FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip curl && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data && \
    curl -sSf -o /app/data/protein_x42.pdb https://files.rcsb.org/download/1L2Y.pdb && \
    curl -sSf -o /app/data/protein_k17.pdb https://files.rcsb.org/download/1CRN.pdb

COPY notes.txt /app/data/notes.txt
COPY analysis_protocol.json /app/data/analysis_protocol.json

WORKDIR /app
