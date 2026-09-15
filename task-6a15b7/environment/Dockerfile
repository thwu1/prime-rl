FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gnuplot-nox \
    && rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py
RUN test -f /data/cases/geometry.dat
RUN test -d /data/cases/mesh_100x50/postProcessing
RUN test -d /data/cases/dp_000.50/postProcessing

WORKDIR /app
