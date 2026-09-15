
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip gfortran && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/fortran/rober /app/fortran/hires /app/fortran/e5 /app/reference

COPY fortran/rober/equation.f /app/fortran/rober/equation.f
COPY fortran/rober/driver_radau5.f /app/fortran/rober/driver_radau5.f
COPY fortran/hires/equation.f /app/fortran/hires/equation.f
COPY fortran/hires/driver_radau5.f /app/fortran/hires/driver_radau5.f
COPY fortran/e5/equation.f /app/fortran/e5/equation.f
COPY fortran/e5/driver_radau5.f /app/fortran/e5/driver_radau5.f
COPY reference/rober_ref.txt /app/reference/rober_ref.txt
COPY reference/hires_ref.txt /app/reference/hires_ref.txt
COPY reference/e5_ref.txt /app/reference/e5_ref.txt

WORKDIR /app
