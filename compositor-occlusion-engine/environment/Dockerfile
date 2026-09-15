FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc make && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/scenarios

COPY invariants.md /app/invariants.md
COPY protocol.md /app/protocol.md
COPY Makefile /app/Makefile
COPY basic.txt /app/scenarios/basic.txt
COPY overlap.txt /app/scenarios/overlap.txt
COPY complex.txt /app/scenarios/complex.txt

WORKDIR /app
