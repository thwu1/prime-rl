FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 trimesh==4.4.0 scipy==1.14.1 Rtree==1.3.0

COPY generate_models.py /tmp/generate_models.py
RUN python3 /tmp/generate_models.py && rm /tmp/generate_models.py

COPY evaluate_buggy.py /app/evaluate.py
COPY spec.md /app/spec.md
COPY pairs.json /app/models/pairs.json

WORKDIR /app
