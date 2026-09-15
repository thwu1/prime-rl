FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 graphviz && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data /app /app/output

COPY data/create_catalog.py /data/create_catalog.py
COPY data/cost_model.py /data/cost_model.py
COPY data/queries.json /data/queries.json
COPY data/main_stub.py /data/main_stub.py

RUN python3 /data/create_catalog.py

WORKDIR /app
