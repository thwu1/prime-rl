
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV TERM=xterm-256color
ENV LANG=C.UTF-8

RUN apt-get update && \
    apt-get install -y python3 python3-pip tmux && \
    rm -rf /var/lib/apt/lists/*

RUN printf '%s\n%s\n%s\n' \
    'set -g default-terminal "tmux-256color"' \
    'set -as terminal-features ",*:RGB"' \
    'set -g status off' > /root/.tmux.conf

RUN mkdir -p /app/fixtures

COPY app/terminal_emulator.py /app/terminal_emulator.py
COPY app/spec.md /app/spec.md
COPY app/fixtures/static_screen.py /app/fixtures/static_screen.py
COPY app/fixtures/interactive_screen.py /app/fixtures/interactive_screen.py

WORKDIR /app
