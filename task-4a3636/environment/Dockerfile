
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 -q

COPY generate_images.py /tmp/generate_images.py
COPY buggy_nfiq2.py /app/nfiq2_features.py

COPY ref_common_functions.cpp /app/reference/common_functions.cpp
COPY ref_fda.cpp /app/reference/fda.cpp
COPY ref_ocl.cpp /app/reference/ocl.cpp
COPY reference_readme.txt /app/reference/README.txt

RUN python3 /tmp/generate_images.py && rm /tmp/generate_images.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3 scipy==1.14.1
