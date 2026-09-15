FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip gcc make gnuplot-nox && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/rhs_native /app/results
WORKDIR /app

COPY problem.py /app/problem.py
COPY brusselator.c /app/rhs_native/brusselator.c
COPY rhs_makefile /app/rhs_native/Makefile

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3 scipy==1.14.1
