FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip sqlite3 curl jq git && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install flask==3.0.3 requests==2.31.0

COPY app/ /app/
COPY setup_environment.py /tmp/setup_environment.py

RUN cd /app && python3 db/init_db.py && python3 db/simulate_incident.py
RUN python3 /tmp/setup_environment.py && rm /tmp/setup_environment.py

WORKDIR /app
