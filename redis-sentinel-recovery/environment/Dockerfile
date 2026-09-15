FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y redis-server redis-tools supervisor python3 python3-pip curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install flask==3.0.0 redis==5.0.1

RUN mkdir -p /etc/redis /data/redis-node-a /data/redis-node-b \
    /var/log/redis /var/run/redis /var/log/supervisor /app

COPY node_a.conf /etc/redis/node_a.conf
COPY node_b.conf /etc/redis/node_b.conf
COPY sentinel1.conf /etc/redis/sentinel1.conf
COPY sentinel2.conf /etc/redis/sentinel2.conf
COPY sentinel3.conf /etc/redis/sentinel3.conf
COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY app.py /app/app.py
COPY reconciliation_rules.md /app/reconciliation_rules.md
COPY setup_node_a.py /tmp/setup_node_a.py
COPY setup_node_b.py /tmp/setup_node_b.py
COPY corrupt_aof.sh /tmp/corrupt_aof.sh
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh /tmp/corrupt_aof.sh && \
    redis-server /etc/redis/node_a.conf --daemonize yes && \
    sleep 2 && \
    python3 /tmp/setup_node_a.py && \
    sleep 2 && \
    (redis-cli -p 6379 -a secretpass SHUTDOWN || true) && \
    sleep 1 && \
    rm -f /data/redis-node-a/dump.rdb && \
    /tmp/corrupt_aof.sh && \
    redis-server /etc/redis/node_b.conf --daemonize yes && \
    sleep 2 && \
    python3 /tmp/setup_node_b.py && \
    redis-cli -p 6380 -a secretpass SAVE && \
    (redis-cli -p 6380 -a secretpass SHUTDOWN || true) && \
    sleep 1 && \
    rm -f /tmp/setup_node_a.py /tmp/setup_node_b.py /tmp/corrupt_aof.sh

ENTRYPOINT []
CMD ["/entrypoint.sh"]
