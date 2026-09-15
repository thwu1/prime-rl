FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-pip python3-dev gcc make && \
    rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/reference /app/libastro

COPY libastro/astro.c /app/libastro/astro.c
COPY libastro/Makefile /app/libastro/Makefile
COPY doodson_coefficients.json /app/doodson_coefficients.json
COPY tidal_engine.py /app/tidal_engine.py
COPY reference/pyTMD_astro_excerpt.py /app/reference/pyTMD_astro_excerpt.py
COPY reference/pyTMD_constituents_excerpt.py /app/reference/pyTMD_constituents_excerpt.py

WORKDIR /app
