FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install qutip==5.3.0 numpy==2.1.3 scipy==1.14.1

COPY system_params.json /app/system_params.json
COPY initial_simulation.py /app/initial_simulation.py

WORKDIR /app
