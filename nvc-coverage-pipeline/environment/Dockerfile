FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential automake autoconf libtool flex check \
    llvm-dev pkg-config zlib1g-dev libdw-dev \
    libffi-dev libzstd-dev git python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch r1.21.0 https://github.com/nickg/nvc.git /tmp/nvc \
    && cd /tmp/nvc \
    && ./autogen.sh \
    && mkdir build && cd /tmp/nvc/build \
    && ../configure \
    && make -j$(nproc) \
    && make install \
    && rm -rf /tmp/nvc

RUN nvc --version

WORKDIR /app
COPY alu.vhd /app/alu.vhd
COPY tb_alu.vhd /app/tb_alu.vhd
