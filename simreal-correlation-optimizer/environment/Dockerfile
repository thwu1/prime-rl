FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/sim

COPY data/sim/ /app/data/sim/
COPY data/real_results.csv /app/data/real_results.csv
COPY data/create_db.py /tmp/create_db.py

RUN python3 /tmp/create_db.py && rm /tmp/create_db.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3 scipy==1.14.1
