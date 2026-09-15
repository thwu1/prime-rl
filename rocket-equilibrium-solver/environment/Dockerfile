FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    gfortran \
    && rm -rf /var/lib/apt/lists/*


COPY thermo_h2o2.dat /app/thermo_h2o2.dat
COPY problem.json /app/problem.json
COPY thermo_eval.f90 /app/thermo_eval.f90

WORKDIR /app
