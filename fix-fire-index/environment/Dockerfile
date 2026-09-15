FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Generate synthetic weather station data and fire occurrence records
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

# Install the buggy CFFWIS calculator
COPY cffwis.py /app/cffwis.py

# Install CFFWIS reference equations
COPY reference_equations.md /app/reference_equations.md
