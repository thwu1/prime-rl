
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y gcc make binutils python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY app/ /app/
WORKDIR /app

RUN make

RUN gcc -o gen_golden gen_golden.c -L. -lrecord && \
    ./gen_golden && \
    rm -f gen_golden gen_golden.c
