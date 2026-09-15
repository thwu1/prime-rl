FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-dev g++ \
    && rm -rf /var/lib/apt/lists/*

# Install clingo build deps with cmake < 3.27 (modern cmake removed
# compatibility with cmake_minimum_required < 3.5 that clingo 5.6.2 needs)
RUN pip3 install cmake==3.26.4 scikit-build==0.17.6 ninja==1.11.1.1 && \
    pip3 install clingo==5.6.2 --no-build-isolation

COPY packages.json /app/packages.json
COPY models.py /app/models.py

WORKDIR /app
