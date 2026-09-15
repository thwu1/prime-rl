FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip jq && rm -rf /var/lib/apt/lists/*

RUN pip3 install torch==2.4.0+cpu --index-url https://download.pytorch.org/whl/cpu --no-cache-dir

RUN mkdir -p /app/output

COPY rotations_lib.py /app/rotations_lib.py
COPY pose_graph.json /app/pose_graph.json

WORKDIR /app
