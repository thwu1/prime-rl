FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    cmake \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pybullet==3.2.6 numpy==1.26.4

WORKDIR /app
COPY workcell_config.json /app/workcell_config.json
