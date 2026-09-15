FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip redis-server && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/hitchhiker

COPY core.py /app/hitchhiker/core.py
COPY init.py /app/hitchhiker/__init__.py
COPY messaging_skeleton.py /app/hitchhiker/messaging.py
COPY overview.md /app/OVERVIEW.md

WORKDIR /app
