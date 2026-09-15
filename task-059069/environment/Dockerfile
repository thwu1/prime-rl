FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    hdf5-tools \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Build-time dependencies for data generation
RUN pip3 install numpy==2.1.3 pyyaml==6.0.2 h5py==3.12.1

# Output format validator
RUN mkdir -p /app/tools
COPY validate_output.py /app/tools/validate_output.py
RUN chmod +x /app/tools/validate_output.py

# Generate synthetic HDF5 walking data and SQLite protocol database
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
