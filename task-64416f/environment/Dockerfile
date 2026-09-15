
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    make \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

COPY ir_interpreter.py /app/ir_interpreter.py
COPY optimize_stub.py /app/optimize.py
COPY Makefile /app/Makefile
COPY programs/ /app/programs/

RUN chmod +x /app/ir_interpreter.py /app/optimize.py

WORKDIR /app
