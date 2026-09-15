
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app

COPY libelliptic.h /app/libelliptic.h
COPY libelliptic.c /app/libelliptic.c
COPY Makefile /app/Makefile
COPY native_binding.py /app/native_binding.py
COPY landen.py /app/landen.py
COPY elliptic_k.py /app/elliptic_k.py
COPY jacobi_cd.py /app/jacobi_cd.py
COPY cd_inverse.py /app/cd_inverse.py
COPY rational.py /app/rational.py
COPY filter_design.py /app/filter_design.py
COPY elliptic_filter.py /app/elliptic_filter.py
COPY scenarios.json /app/scenarios.json

WORKDIR /app

RUN make
