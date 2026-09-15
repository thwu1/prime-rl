FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    procps \
    redis-server \
    redis-tools \
    nmap \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install flask==3.0.3 redis==5.0.0 --no-cache-dir

WORKDIR /app

COPY app.py /app/app.py
COPY start_server.sh /app/start_server.sh
RUN chmod +x /app/start_server.sh

CMD ["bash", "-c", "/app/start_server.sh; exec sleep infinity"]
