FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y gcc binutils && rm -rf /var/lib/apt/lists/*
COPY target.c /tmp/target.c
RUN gcc -c -O0 -fno-stack-protector -fno-pic -fcf-protection=none -std=c11 \
    -o /tmp/target.o /tmp/target.c

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y gcc binutils python3-pip && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app
COPY --from=builder /tmp/target.o /app/target.o
COPY candidate.c /app/candidate.c
