FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc make sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/correlations

COPY scenarios.toml /app/scenarios.toml
COPY Makefile /app/Makefile
COPY pipeline.py /app/pipeline.py
COPY settling.py /app/settling.py
COPY fluidization.py /app/fluidization.py
COPY correlations/__init__.py /app/correlations/__init__.py
COPY correlations/viscous_inertial.py /app/correlations/viscous_inertial.py
COPY correlations/empirical.py /app/correlations/empirical.py
COPY correlations/advanced.py /app/correlations/advanced.py
COPY correlations/wall_corrected.py /app/correlations/wall_corrected.py
COPY correlations/native_impl.c /app/correlations/native_impl.c
COPY correlations/native.py /app/correlations/native.py

WORKDIR /app
