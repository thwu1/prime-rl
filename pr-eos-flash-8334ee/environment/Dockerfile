FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc make && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pr_eos /app/reference_data /app/libcubic

COPY pr_eos/__init__.py /app/pr_eos/__init__.py
COPY pr_eos/constants.py /app/pr_eos/constants.py
COPY pr_eos/pure.py /app/pr_eos/pure.py
COPY pr_eos/mixing.py /app/pr_eos/mixing.py
COPY pr_eos/cubic.py /app/pr_eos/cubic.py
COPY pr_eos/fugacity.py /app/pr_eos/fugacity.py
COPY pr_eos/flash.py /app/pr_eos/flash.py

COPY libcubic/cubic_solver.c /app/libcubic/cubic_solver.c
COPY libcubic/Makefile /app/libcubic/Makefile

COPY reference_data/hexane_pure.json /app/reference_data/hexane_pure.json
COPY reference_data/n2_ch4_binary.json /app/reference_data/n2_ch4_binary.json
COPY reference_data/n2_ch4_supercritical.json /app/reference_data/n2_ch4_supercritical.json
COPY reference_data/ternary_elliott.json /app/reference_data/ternary_elliott.json
COPY reference_data/c2_c5_flash.json /app/reference_data/c2_c5_flash.json
COPY reference_data/ch4_h2s_flash.json /app/reference_data/ch4_h2s_flash.json

WORKDIR /app
