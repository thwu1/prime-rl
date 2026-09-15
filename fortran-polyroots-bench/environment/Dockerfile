FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y gfortran liblapack-dev libblas-dev git wget python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Install fpm (Fortran Package Manager) - try binary, fall back to source bootstrap
RUN wget -q -O /usr/local/bin/fpm \
      https://github.com/fortran-lang/fpm/releases/download/v0.10.1/fpm-0.10.1-linux-x86_64 && \
      chmod +x /usr/local/bin/fpm && \
      fpm --version || \
    ( rm -f /usr/local/bin/fpm && \
      wget -q -O /usr/local/bin/fpm \
        https://github.com/fortran-lang/fpm/releases/download/v0.10.0/fpm-0.10.0-linux-x86_64 && \
      chmod +x /usr/local/bin/fpm && \
      fpm --version ) || \
    ( rm -f /usr/local/bin/fpm && \
      echo "Binary download failed, compiling fpm from single-file source..." && \
      wget -q -O /tmp/fpm.F90 \
        https://github.com/fortran-lang/fpm/releases/download/v0.10.0/fpm-0.10.0.F90 && \
      gfortran -O2 -o /usr/local/bin/fpm /tmp/fpm.F90 && \
      rm -f /tmp/fpm.F90 && \
      fpm --version ) || \
    echo "WARNING: fpm installation failed; gfortran manual compilation remains available"

# Pre-clone polyroots-fortran so it can be used as a local dependency or compiled directly
RUN git clone --depth=1 https://github.com/jacobwilliams/polyroots-fortran.git /opt/polyroots-fortran

RUN mkdir -p /app
WORKDIR /app
