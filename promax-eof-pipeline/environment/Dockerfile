
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip python3-numpy python3-scipy netcdf-bin nco && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install xarray==2024.10.0 netCDF4==1.7.2

RUN mkdir -p /app/pipeline /app/reference

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY generate_reference.py /tmp/generate_reference.py
RUN python3 /tmp/generate_reference.py && rm /tmp/generate_reference.py

COPY pipeline_init.py /app/pipeline/__init__.py
COPY preprocess_buggy.py /app/pipeline/preprocess.py
COPY decompose_buggy.py /app/pipeline/decompose.py
COPY rotate_stub.py /app/pipeline/rotate.py
COPY postprocess_buggy.py /app/pipeline/postprocess.py
COPY run_analysis.py /app/run_analysis.py

WORKDIR /app
