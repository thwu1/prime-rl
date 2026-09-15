FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gfortran \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


COPY taboo.f90 /app/taboo.f90
COPY model_spec.json /app/model_spec.json

RUN mkdir -p /app/output

WORKDIR /app
