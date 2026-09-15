
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONPATH=/opt/son_ir:/app

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/son_ir /app
COPY app/ir.py /opt/son_ir/ir.py
COPY app/ir.py /app/ir.py
COPY app/codegen.py /app/codegen.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
