FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip gcc make && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/sgwt_lib /app/sgwt_native /app/docs

COPY graph_spec.json /app/graph_spec.json
COPY run_sgwt.py /app/run_sgwt.py
COPY Makefile /app/Makefile
COPY sgwt_native/cheby.c /app/sgwt_native/cheby.c
COPY sgwt_native/sgwt_native.h /app/sgwt_native/sgwt_native.h
COPY sgwt_lib/__init__.py /app/sgwt_lib/__init__.py
COPY sgwt_lib/graph.py /app/sgwt_lib/graph.py
COPY sgwt_lib/kernels.py /app/sgwt_lib/kernels.py
COPY sgwt_lib/scales.py /app/sgwt_lib/scales.py
COPY sgwt_lib/filtering.py /app/sgwt_lib/filtering.py
COPY sgwt_lib/frames.py /app/sgwt_lib/frames.py
COPY sgwt_lib/jackson.py /app/sgwt_lib/jackson.py
COPY docs/spectral_graph_theory.md /app/docs/spectral_graph_theory.md
COPY docs/wavelet_kernels.md /app/docs/wavelet_kernels.md
COPY docs/polynomial_approximation.md /app/docs/polynomial_approximation.md

WORKDIR /app
