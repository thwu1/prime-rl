FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip octave make && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

COPY octave/phifun.m /app/octave/phifun.m
COPY octave/ks_setup.m /app/octave/ks_setup.m
COPY problem.py /app/problem.py
COPY spec.md /app/spec.md
COPY Makefile /app/Makefile

WORKDIR /app
