FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    python3 \
    python3-pip \
    libssl-dev \
    pkg-config \
    binutils \
    && rm -rf /var/lib/apt/lists/*

# Install fake dependency library headers (IceCompat, NetStream)
COPY deps/icecompat/ /usr/include/icecompat/
COPY deps/netstream/ /usr/include/netstream/

# Set up the project source with bugs
COPY project/ /app/
COPY buildlog.txt /app/buildlog.txt

WORKDIR /app
