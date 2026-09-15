FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/ch4_mof5.json /app/data/ch4_mof5.json
COPY data/c2h6_mof5.json /app/data/c2h6_mof5.json
COPY data/butane_298K.json /app/data/butane_298K.json
COPY data/butane_323K.json /app/data/butane_323K.json
COPY data/butane_348K.json /app/data/butane_348K.json

WORKDIR /app
