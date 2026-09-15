FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/reference

COPY generate_data.py /app/generate_data.py
COPY microstructure_skeleton.py /app/microstructure.py
COPY run_simulation_skeleton.py /app/run_simulation.py
COPY queue.rs /app/reference/queue.rs
COPY spec.md /app/reference/spec.md

RUN python3 /app/generate_data.py

WORKDIR /app
