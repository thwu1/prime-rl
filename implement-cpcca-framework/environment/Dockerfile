FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip hdf5-tools make && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 h5py==3.12.1

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY cross_decomp.py /app/cross_decomp.py
COPY pipeline.py /app/pipeline.py
COPY validate_results.py /app/validate_results.py
COPY Makefile /app/Makefile

WORKDIR /app
