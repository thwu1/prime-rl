FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    sqlite3 \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install flask==3.1.0 pyyaml==6.0.2 requests==2.32.3

COPY app/ /app/

RUN mkdir -p /app/logs /app/data

RUN chmod +x /app/scripts/start_all.sh

RUN python3 /app/scripts/setup_db.py

RUN python3 /app/scripts/generate_logs.py

WORKDIR /app
