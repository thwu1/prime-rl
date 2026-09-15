FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    make \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --branch v6.0.0 https://github.com/BieremaBoyzProgramming/bbpPairings.git /app/bbpPairings-src \
    && cd /app/bbpPairings-src \
    && make -j$(nproc) \
    && cp bbpPairings.exe /app/bbpPairings.exe

COPY players.csv /app/players.csv
COPY setup_tournament.py /tmp/setup_tournament.py

RUN python3 /tmp/setup_tournament.py && rm /tmp/setup_tournament.py

WORKDIR /app
