
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    nasm \
    xxd \
    && rm -rf /var/lib/apt/lists/*

COPY programs/ /tmp/programs/

RUN mkdir -p /app/programs && \
    for f in /tmp/programs/*.asm; do \
        name=$(basename "$f" .asm); \
        nasm -f bin -Ox "$f" -o "/app/programs/${name}.bin" || exit 1; \
    done && \
    rm -rf /tmp/programs

WORKDIR /app
