FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3-pip \
    sqlite3 \
    procps \
    curl \
    tshark \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install flask==3.1.1 requests==2.32.3

COPY app/ /app/
COPY setup_and_break.py /tmp/setup_and_break.py

RUN python3 /tmp/setup_and_break.py && rm -f /tmp/setup_and_break.py

WORKDIR /app
