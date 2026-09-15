FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/aero /app/libvortex /data

COPY libvortex/vortex.h /app/libvortex/vortex.h
COPY libvortex/biot_savart.c /app/libvortex/biot_savart.c
COPY libvortex/Makefile /app/libvortex/Makefile

COPY aero/__init__.py /app/aero/__init__.py
COPY aero/biot_savart.py /app/aero/biot_savart.py
COPY aero/panel.py /app/aero/panel.py
COPY aero/aic.py /app/aero/aic.py
COPY aero/forces.py /app/aero/forces.py
COPY aero/solver.py /app/aero/solver.py

COPY vlm_solver.py /app/vlm_solver.py
COPY config.json /data/config.json
COPY config.json /app/config.json

WORKDIR /app
