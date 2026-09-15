
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    gcc \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

# Install ObsPy framework (task environment — seismological tools)
RUN pip3 install numpy==1.26.4 scipy==1.13.1 obspy==1.4.1

# Generate synthetic observation data
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
