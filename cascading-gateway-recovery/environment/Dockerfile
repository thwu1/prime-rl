FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y \
        python3 \
        python3-pip \
        sqlite3 \
        haproxy \
        supervisor \
        curl \
        net-tools \
        procps && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/services /app/config /app/data /app/logs /app/scripts

COPY services/gateway_worker.py /app/services/gateway_worker.py
COPY services/config_pusher.py /app/services/config_pusher.py
COPY services/monitor.py /app/services/monitor.py

COPY config/supervisord.conf /app/config/supervisord.conf
COPY config/haproxy.cfg /app/config/haproxy.cfg

COPY scripts/init_system.py /app/scripts/init_system.py
RUN python3 /app/scripts/init_system.py

WORKDIR /app
