FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY dirichlet.c /app/dirichlet.c
COPY dirichlet.h /app/dirichlet.h
COPY compute.py /app/compute.py
COPY Makefile /app/Makefile
COPY spec.txt /app/spec.txt
COPY naive.py /app/naive.py

RUN cd /app && make

WORKDIR /app
