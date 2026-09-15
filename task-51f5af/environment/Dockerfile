
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY x86_ast.py graph.py priority_queue.py emulator.py programs.py /app/
COPY allocator.py codegen.py /app/
COPY runtime.c Makefile compile_driver.py /app/
