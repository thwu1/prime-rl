
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
    blender \
    python3-pip \
    xvfb \
    libgl1-mesa-dri \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/output

COPY targets.json /app/targets.json
