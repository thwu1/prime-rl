FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/programs

COPY spec.md /app/spec.md
COPY Makefile /app/Makefile
COPY programs/basic.lang /app/programs/basic.lang
COPY programs/branch.lang /app/programs/branch.lang
COPY programs/loop.lang /app/programs/loop.lang
COPY programs/interproc.lang /app/programs/interproc.lang
COPY programs/context.lang /app/programs/context.lang

WORKDIR /app
