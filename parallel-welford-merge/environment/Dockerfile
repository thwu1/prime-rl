FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

# Copy application source files
COPY config.json /app/config.json
COPY parallel_reduce.py /app/parallel_reduce.py
COPY simulator/ /app/simulator/
COPY layout_tool.py /app/layout_tool.py
COPY generate_data.py /tmp/generate_data.py

# Remove stale bytecode cache, then generate deterministic datasets
RUN rm -rf /app/simulator/__pycache__ && python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app

