FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gfortran \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY pekeris_solver.f90 /app/pekeris_solver.f90
COPY main.f90 /app/main.f90
COPY waveguide.cfg /app/waveguide.cfg
COPY Makefile /app/Makefile

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 scipy==1.14.1 numpy==2.1.3
