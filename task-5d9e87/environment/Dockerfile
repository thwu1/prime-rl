FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    libgl1 \
    libglu1-mesa \
    libxmu6 \
    libxi6 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 cadquery==2.4.0

COPY parts/ /app/parts/
COPY assembly_spec.json /app/assembly_spec.json

WORKDIR /app
