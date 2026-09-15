FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    libcairo2-dev \
    libffi-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install cairosvg==2.7.1 Pillow==10.4.0 numpy==2.1.3 scikit-image==0.24.0

RUN mkdir -p /app/dataset /app/output /app/spec /app/pipeline

COPY app/dataset/pairs.json /app/dataset/pairs.json
COPY app/spec/methodology.md /app/spec/methodology.md
COPY app/spec/output_schema.json /app/spec/output_schema.json

COPY app/pipeline_buggy/ /app/pipeline/

WORKDIR /app
