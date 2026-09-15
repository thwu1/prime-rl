
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gfortran \
    liblapack-dev \
    libblas-dev \
    git \
    curl \
    python3 \
    python3-pip \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install fpm (Fortran Package Manager)
RUN curl -fsSL "https://github.com/fortran-lang/fpm/releases/download/v0.10.1/fpm-0.10.1-linux-x86_64" -o /usr/local/bin/fpm \
    && chmod +x /usr/local/bin/fpm

RUN mkdir -p /app/fortran_bench/app

# Generate challenge data (numpy used only for data generation, then removed)
COPY setup_data.py /tmp/setup_data.py
RUN pip3 install numpy==2.1.3 -q \
    && python3 /tmp/setup_data.py \
    && pip3 uninstall -y numpy -q \
    && rm /tmp/setup_data.py

# Set up skeleton fpm project for polyroots-fortran benchmarking
COPY fpm_bench.toml /app/fortran_bench/fpm.toml
COPY main_stub.f90 /app/fortran_bench/app/main.f90

WORKDIR /app
