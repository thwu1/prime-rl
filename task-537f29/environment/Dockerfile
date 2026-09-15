FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS assembler
RUN apt-get update && apt-get install -y nasm && rm -rf /var/lib/apt/lists/*
COPY test1.asm test2.asm test3.asm test4.asm test5.asm test6.asm /tmp/
RUN mkdir -p /out && \
    nasm /tmp/test1.asm -o /out/test1 && \
    nasm /tmp/test2.asm -o /out/test2 && \
    nasm /tmp/test3.asm -o /out/test3 && \
    nasm /tmp/test4.asm -o /out/test4 && \
    nasm /tmp/test5.asm -o /out/test5 && \
    nasm /tmp/test6.asm -o /out/test6

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    nasm \
    build-essential \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/programs
COPY --from=assembler /out/ /app/programs/

WORKDIR /app
