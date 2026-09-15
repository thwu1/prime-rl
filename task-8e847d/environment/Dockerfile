FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip tcpdump iproute2 strace lsof net-tools && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

RUN mkdir -p /app/backends

COPY config.yaml /app/config.yaml
COPY echo_server.py /app/backends/echo_server.py
COPY lb_deployed.py /app/lb.py

WORKDIR /app
