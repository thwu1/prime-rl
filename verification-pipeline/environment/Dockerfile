FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/specs /app/config /app/roots

COPY app/parser_notes.py /app/parser_notes.py
COPY app/specs/ /app/specs/
COPY app/config/ /app/config/
COPY app/roots/ /app/roots/

WORKDIR /app
