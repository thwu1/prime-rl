FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

COPY data/ /tmp/build_data/

RUN python3 /tmp/build_data/setup_db.py && cp /tmp/build_data/output_spec.json /app/output_spec.json && rm -rf /tmp/build_data

WORKDIR /app
