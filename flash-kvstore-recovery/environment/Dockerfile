FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tickv_ref

COPY flash_sim.py /app/flash_sim.py
COPY tickv_ref/tickv.h /app/tickv_ref/tickv.h
COPY tickv_ref/tickv.c /app/tickv_ref/tickv.c
COPY tickv_ref/tickv_tool.c /app/tickv_ref/tickv_tool.c

RUN gcc -O2 -Wall -o /app/tickv_ref/tickv_tool \
    /app/tickv_ref/tickv.c /app/tickv_ref/tickv_tool.c

WORKDIR /app
