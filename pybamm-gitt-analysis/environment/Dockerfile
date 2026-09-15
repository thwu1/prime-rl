
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    gfortran \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pybamm==26.5.0

WORKDIR /app
COPY gitt_pipeline.py /app/gitt_pipeline.py
