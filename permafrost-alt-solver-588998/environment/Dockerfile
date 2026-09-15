FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip gfortran make file && rm -rf /var/lib/apt/lists/*

COPY config.toml /app/config.toml
COPY pipeline.py /app/pipeline.py
COPY ["thermal_lib/thermal.f90", "/app/thermal_lib/thermal.f90"]
COPY ["thermal_lib/Makefile", "/app/thermal_lib/Makefile"]
COPY ["data/thermal_parameters.csv", "/app/data/thermal_parameters.csv"]
COPY ["reference/ku_model.py", "/app/reference/ku_model.py"]
COPY ["reference/frost_number.py", "/app/reference/frost_number.py"]
COPY ["reference/README.md", "/app/reference/README.md"]

WORKDIR /app
