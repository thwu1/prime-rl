FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    binutils \
    gdb \
    nasm \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/son_ir

COPY app/son_ir/__init__.py /app/son_ir/__init__.py
COPY app/son_ir/nodes.py /app/son_ir/nodes.py
COPY app/son_ir/graph.py /app/son_ir/graph.py
COPY app/son_ir/evaluator.py /app/son_ir/evaluator.py

RUN python3 -c "import sys; sys.path.insert(0, '/app'); from son_ir.graph import Graph; print('son_ir verified')"

WORKDIR /app
