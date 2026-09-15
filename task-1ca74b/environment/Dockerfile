FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    g++ \
    clang \
    llvm \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/spec /app/lib /app/programs

COPY parser.py /app/parser.py
RUN chmod +x /app/parser.py

COPY setup_task.py /tmp/setup_task.py
RUN python3 /tmp/setup_task.py && rm /tmp/setup_task.py

WORKDIR /app
