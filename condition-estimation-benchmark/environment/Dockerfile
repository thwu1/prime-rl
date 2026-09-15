FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gcc \
    make \
    liblapack-dev \
    libblas-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 -q

RUN mkdir -p /app/c_src
COPY config.json /app/config.json
COPY matrices.py /app/matrices.py
COPY estimators.py /app/estimators.py
COPY benchmark.py /app/benchmark.py
COPY blocked_est.c /app/c_src/blocked_est.c
COPY csrc_Makefile /app/c_src/Makefile

WORKDIR /app
RUN python3 benchmark.py
