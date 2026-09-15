FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONPATH="/opt/task_lib:/app"


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tmux \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/task_lib
COPY app/terminal.py /opt/task_lib/terminal.py
COPY app/terminal.py /app/terminal.py
COPY app/diff_engine.py /app/diff_engine.py
COPY app/tmux_validator.py /app/tmux_validator.py
WORKDIR /app
