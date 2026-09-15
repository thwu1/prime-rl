FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/json /app/data/edn /app/docs

COPY data_json/ /app/data/json/
COPY data_edn/ /app/data/edn/
COPY checker.py /app/checker.py
COPY ground_truth.json /app/ground_truth.json
COPY isolation_reference.txt /app/docs/isolation_reference.txt
COPY init_db.py /tmp/init_db.py

RUN python3 /tmp/init_db.py && rm /tmp/init_db.py

WORKDIR /app
