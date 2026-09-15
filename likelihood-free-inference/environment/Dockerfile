FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc libhdf5-dev hdf5-tools pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY simulator.c /tmp/simulator.c
RUN gcc -O2 -o /app/simulator /tmp/simulator.c -lm && rm /tmp/simulator.c && chmod +x /app/simulator

COPY setup_observations.py /tmp/setup_observations.py
RUN pip3 install numpy==2.1.3 h5py==3.12.1 -q && python3 /tmp/setup_observations.py && rm /tmp/setup_observations.py

WORKDIR /app
