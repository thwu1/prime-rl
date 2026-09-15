FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 netCDF4==1.7.2

COPY gen_data.py /tmp/gen_data.py
RUN mkdir -p /app/data /app/output && python3 /tmp/gen_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    nco \
    netcdf-bin \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/data /app/data
RUN mkdir -p /app/output

WORKDIR /app
