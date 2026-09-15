FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/kernel_sim /app/configs

COPY kernel_sim/__init__.py /app/kernel_sim/__init__.py
COPY kernel_sim/grid.py /app/kernel_sim/grid.py
COPY kernel_sim/cache_model.py /app/kernel_sim/cache_model.py
COPY kernel_sim/hardware.py /app/kernel_sim/hardware.py
COPY kernel_sim/scheduler.py /app/kernel_sim/scheduler.py
COPY configs/h100.json /app/configs/h100.json
COPY run_analysis.py /app/run_analysis.py

WORKDIR /app
