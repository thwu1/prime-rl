FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 numcodecs==0.14.0 zarr==2.18.2

WORKDIR /app

COPY create_stores.py /tmp/create_stores.py
RUN python3 /tmp/create_stores.py && rm /tmp/create_stores.py

COPY rechunker.py /app/rechunker.py
COPY cost_model.py /app/cost_model.py
COPY zarr_inspector.py /app/zarr_inspector.py
COPY arrays.json /app/arrays.json
COPY evaluate.py /app/evaluate.py

