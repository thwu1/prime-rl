FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gfortran \
    && rm -rf /var/lib/apt/lists/*


COPY taboo.f90 /app/reference/taboo.f90
COPY sample_log.txt /app/reference/sample_log.txt
COPY earth_model.dat /app/data/earth_model.dat

RUN mkdir -p /app/output

WORKDIR /app
