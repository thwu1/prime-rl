
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    octave \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1

RUN mkdir -p /app/models /app/results /app/octave_ref

COPY frame3d_buggy.py /app/frame3d.py
COPY reference.md /app/reference.md
COPY validate.py /app/validate.py
COPY process_model.py /app/process_model.py
COPY models/cantilever_circular.toml /app/models/cantilever_circular.toml
COPY octave_ref/verify_kg.m /app/octave_ref/verify_kg.m

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
