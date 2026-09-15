FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    python3 \
    python3-pip \
    procps \
    net-tools \
    strace \
    lsof \
    gdb \
    ltrace \
    netcat-openbsd \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/config /app/services /var/log/collector

COPY collector.c /app/collector.c
COPY endpoints.conf /app/config/endpoints.conf
COPY svc_binary.py /app/services/svc_binary.py
COPY svc_http.py /app/services/svc_http.py
COPY start_services.sh /app/start_services.sh
COPY watchdog.sh /app/watchdog.sh
COPY collector_log.txt /var/log/collector/collector.log
COPY watchdog_log.txt /var/log/collector/watchdog.log

RUN chmod +x /app/start_services.sh /app/watchdog.sh

RUN gcc -o /app/collector /app/collector.c

WORKDIR /app
