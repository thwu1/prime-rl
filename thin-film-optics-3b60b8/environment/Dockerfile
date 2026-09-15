FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip gcc make sqlite3 && rm -rf /var/lib/apt/lists/*


COPY app/tmm_engine.py /app/tmm_engine.py
COPY app/matrix_kernel.c /app/matrix_kernel.c
COPY app/stacks.yaml /app/stacks.yaml
COPY app/reference/ /app/reference/

WORKDIR /app
