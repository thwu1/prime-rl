FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONPATH=/app:/opt/transport_lib


RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip gnuplot-nox && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/transport_lib

COPY app/channel.py app/packet.py app/harness.py /opt/transport_lib/
COPY app/ /app/

WORKDIR /app
