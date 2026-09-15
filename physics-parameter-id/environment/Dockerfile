FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip python3-dev build-essential cmake && rm -rf /var/lib/apt/lists/*
RUN pip3 install pybullet==3.2.6 numpy==1.26.4
RUN mkdir -p /app
COPY generate_observations.py /tmp/generate_observations.py
RUN python3 /tmp/generate_observations.py && rm -f /tmp/generate_observations.py
WORKDIR /app
