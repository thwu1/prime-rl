FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip gcc make gnuplot-nox && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY network_a.s2p /app/network_a.s2p
COPY network_b.ts /app/network_b.ts
COPY config.json /app/config.json
COPY matrix_ops.c /app/matrix_ops.c
COPY matrix_ops.h /app/matrix_ops.h
COPY Makefile /app/Makefile

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==1.26.4
