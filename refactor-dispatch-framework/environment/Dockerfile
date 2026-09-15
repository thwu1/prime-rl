
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
        build-essential \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY src/types.h /app/types.h
COPY src/types.c /app/types.c
COPY src/dispatch.h /app/dispatch.h
COPY src/dispatch.c /app/dispatch.c
COPY src/handlers.h /app/handlers.h
COPY src/handlers.c /app/handlers.c
COPY src/main.c /app/main.c
COPY src/Makefile /app/Makefile

WORKDIR /app

RUN make && ./cmdproc > /dev/null 2>&1 && make clean
