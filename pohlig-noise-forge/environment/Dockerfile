FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# System packages
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Cryptographic libraries required by the VaultSync server code
RUN pip3 install pycryptodome==3.21.0 tinyec==0.4.0 dissononce==0.34.3

# Copy server code
RUN mkdir -p /app
COPY vaultsync.py /app/vaultsync.py

# Run setup to generate challenge data, then remove the setup script
COPY setup.py /tmp/setup.py
RUN python3 /tmp/setup.py && rm /tmp/setup.py

WORKDIR /app
