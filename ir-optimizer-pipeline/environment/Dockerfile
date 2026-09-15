
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/passes

COPY ir.py /app/ir.py
COPY ir_interpreter.py /app/ir_interpreter.py
COPY programs.py /app/programs.py
COPY optimizer.py /app/optimizer.py
COPY passes_init.py /app/passes/__init__.py
COPY ircc /usr/local/bin/ircc

RUN chmod +x /usr/local/bin/ircc

WORKDIR /app
