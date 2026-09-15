
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    pkg-config \
    libnetcdf-dev \
    libhdf5-dev \
    libudunits2-dev \
    libudunits2-0 \
    libgeos-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 cython==3.0.10
RUN pip3 install compliance-checker==5.4.2

RUN mkdir -p /app
COPY create_dataset.py /tmp/create_dataset.py
RUN python3 /tmp/create_dataset.py && rm /tmp/create_dataset.py

WORKDIR /app
