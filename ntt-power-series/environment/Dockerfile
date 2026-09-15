FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc make valgrind && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY ntt.c /app/ntt.c
COPY ntt.h /app/ntt.h
COPY Makefile /app/Makefile
COPY ntt_binding.py /app/ntt_binding.py
COPY mod_arith.py /app/mod_arith.py
COPY fps.py /app/fps.py

WORKDIR /app
