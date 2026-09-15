FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc make && rm -rf /var/lib/apt/lists/*

COPY app/ /opt/hpc_framework/
RUN mkdir -p /app/configs /app/kernels && \
    cp /opt/hpc_framework/*.py /app/ && \
    cp /opt/hpc_framework/Makefile /app/ && \
    cp /opt/hpc_framework/configs/*.json /app/configs/ && \
    cp /opt/hpc_framework/kernels/*.c /app/kernels/

WORKDIR /app
