FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

RUN pip3 install xxhash==3.5.0 -q
COPY setup/init_db.py /tmp/init_db.py
RUN python3 /tmp/init_db.py && pip3 uninstall xxhash -y && rm /tmp/init_db.py

WORKDIR /app
