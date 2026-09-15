FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gcc-mingw-w64-i686 \
    gcc-mingw-w64-x86-64 \
    binutils-mingw-w64-i686 \
    binutils-mingw-w64-x86-64 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/build_src /app/samples

COPY hello32.c /app/build_src/hello32.c
COPY multi64.c /app/build_src/multi64.c
COPY mathlib.c /app/build_src/mathlib.c

WORKDIR /app
