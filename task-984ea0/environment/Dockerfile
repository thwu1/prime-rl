
# Stage 1: Generate reference data using the correct solver
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS reference_builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3 h5py==3.12.1
COPY generate_reference.py /tmp/generate_reference.py
RUN python3 /tmp/generate_reference.py

# Stage 2: Task environment
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    gcc \
    make \
    hdf5-tools \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3 h5py==3.12.1
RUN mkdir -p /app/data /app/src
COPY --from=reference_builder /tmp/reference.h5 /app/data/reference.h5
COPY solver.py /app/solver.py
COPY evaluate.py /app/evaluate.py
COPY kernels.h /app/src/kernels.h
COPY kernels.c /app/src/kernels.c
COPY Makefile_src /app/src/Makefile
WORKDIR /app
