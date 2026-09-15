FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    gdb \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


COPY basicop.h /app/basicop.h
COPY basicop.c /app/basicop.c
COPY oper_32b.h /app/oper_32b.h
COPY oper_32b.c /app/oper_32b.c
COPY levinson.h /app/levinson.h
COPY levinson.c /app/levinson.c
COPY pipeline.c /app/pipeline.c
COPY selftest.c /app/selftest.c
COPY Makefile /app/Makefile

WORKDIR /app
