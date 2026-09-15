FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3-yaml sqlite3 jq && rm -rf /var/lib/apt/lists/*

# Data format libraries needed to generate and work with task artifacts
RUN pip3 install numpy==2.1.3 h5py==3.11.0 pyarrow==17.0.0 duckdb==1.1.0

COPY setup_experiments.py /tmp/setup_experiments.py
RUN python3 /tmp/setup_experiments.py && rm /tmp/setup_experiments.py

WORKDIR /app
