FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/include /app/sys /app/tools /app/docs

COPY files/include/vdma.h /app/include/vdma.h
COPY files/sys/vdma.txt /app/sys/vdma.txt
COPY files/tools/syzlang_lint.py /app/tools/syzlang_lint.py
COPY files/docs/syzlang_syntax.md /app/docs/syzlang_syntax.md

WORKDIR /app
