FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq make && \
    rm -rf /var/lib/apt/lists/*

COPY game.py players.py ai_player.py evaluate.py Makefile setup_baseline.py /app/

WORKDIR /app

RUN python3 setup_baseline.py && rm setup_baseline.py
