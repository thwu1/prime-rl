
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip postgresql postgresql-client && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY setup_db.sh /tmp/setup_db.sh
COPY generate_db.py /tmp/generate_db.py
RUN chmod +x /tmp/setup_db.sh && /tmp/setup_db.sh && rm /tmp/setup_db.sh /tmp/generate_db.py

WORKDIR /app
