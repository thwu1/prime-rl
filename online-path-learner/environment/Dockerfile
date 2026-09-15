FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc g++ make binutils \
    strace ltrace gdb \
    && rm -rf /var/lib/apt/lists/*

COPY judge.c /tmp/judge.c
RUN gcc -O2 -o /app/judge /tmp/judge.c -lm && \
    strip /app/judge && \
    rm -f /tmp/judge.c

COPY problem.txt /app/problem.txt
RUN chmod 555 /app/judge

WORKDIR /app
