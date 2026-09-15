FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gnuplot-nox make hdf5-tools && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 h5py==3.12.1

RUN mkdir -p /app

COPY euler_fv.py /app/euler_fv.py
COPY config.json /app/config.json
COPY generate_ic.py /tmp/generate_ic.py
RUN python3 /tmp/generate_ic.py && rm /tmp/generate_ic.py

WORKDIR /app
