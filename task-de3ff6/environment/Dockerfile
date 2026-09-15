FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Store infrastructure modules in a safe location that persists at runtime
RUN mkdir -p /opt/task_lib
COPY app/programs.py /opt/task_lib/programs.py
COPY app/emulator.py /opt/task_lib/emulator.py
COPY app/graph.py /opt/task_lib/graph.py
COPY app/priority_queue.py /opt/task_lib/priority_queue.py
COPY app/runtime.c /opt/task_lib/runtime.c

# Provide files at /app for the agent to read and use
COPY app/ /app/

ENV PYTHONPATH="/opt/task_lib:/app"

WORKDIR /app
