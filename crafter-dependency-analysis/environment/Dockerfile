FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip graphviz sqlite3 jq && rm -rf /var/lib/apt/lists/*

COPY crafter/ /app/crafter/
COPY create_db.py /tmp/create_db.py
RUN python3 /tmp/create_db.py && rm /tmp/create_db.py

WORKDIR /app
