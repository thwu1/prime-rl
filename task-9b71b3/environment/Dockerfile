FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip git build-essential gfortran \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth=1 --single-branch --branch=v0.22.0 https://github.com/spack/spack.git /opt/spack

ENV SPACK_ROOT=/opt/spack
ENV PATH="$SPACK_ROOT/bin:$PATH"

RUN spack compiler find --scope=site
RUN spack bootstrap now

COPY repo/ /app/repo/
COPY requirements.md /app/requirements.md
COPY env/ /app/env/

WORKDIR /app
