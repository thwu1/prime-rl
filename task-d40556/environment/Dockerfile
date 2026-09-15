FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    make \
    perl \
    git \
    python3-pip \
    bc \
    && rm -rf /var/lib/apt/lists/*

# Build SCTK from source - need config, all, AND install to populate bin/
WORKDIR /opt
RUN git clone https://github.com/usnistgov/SCTK.git && \
    cd SCTK && \
    make config && \
    make all && \
    make install && \
    cp bin/* /usr/local/bin/

# Generate task data
WORKDIR /app
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

RUN mkdir -p /app/results
