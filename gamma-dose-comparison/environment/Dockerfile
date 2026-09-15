FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip gcc make sqlite3 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/accel

COPY reference/ /app/reference/
COPY data/ /app/data/
