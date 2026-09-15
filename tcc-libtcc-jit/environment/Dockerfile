FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    python3-pip \
    texinfo \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://repo.or.cz/tinycc.git /app/tcc-src

COPY input.json /app/input.json
COPY series_jit.c /app/series_jit.c

WORKDIR /app
