FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/src /app/data

COPY CMakeLists.txt /app/CMakeLists.txt
COPY src/main.c /app/src/main.c
COPY src/inchikey.c /app/src/inchikey.c
COPY src/inchikey.h /app/src/inchikey.h
COPY src/sha256.c /app/src/sha256.c
COPY src/sha256.h /app/src/sha256.h
COPY src/sdf_parser.c /app/src/sdf_parser.c
COPY src/sdf_parser.h /app/src/sdf_parser.h
COPY src/dedup.c /app/src/dedup.c
COPY src/dedup.h /app/src/dedup.h
COPY data/molecules.sdf /app/data/molecules.sdf
COPY data/inchi_list.txt /app/data/inchi_list.txt

WORKDIR /app
