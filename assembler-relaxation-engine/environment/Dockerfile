
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc make python3 python3-pip binutils \
    && rm -rf /var/lib/apt/lists/*

COPY assembler.h main.c parser.c layout.c output.c Makefile /app/
COPY spec.md /app/spec.md
COPY programs/ /app/programs/
COPY ref/ /app/ref/

WORKDIR /app
RUN make
