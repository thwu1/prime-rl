FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/data /app/output

COPY data/Ni.stru /app/data/Ni.stru
COPY data/Ni_primitive.stru /app/data/Ni_primitive.stru
COPY data/Ni.cif /app/data/Ni.cif

WORKDIR /app
