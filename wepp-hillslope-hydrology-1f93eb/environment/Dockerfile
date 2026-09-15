FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip sqlite3 gfortran gnuplot-nox && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/reference /app/scenarios /app/stations /app/fortran /app/plots

COPY reference/equations.md /app/reference/equations.md
COPY reference/par_format.md /app/reference/par_format.md
COPY stations/lafayette.par /app/stations/lafayette.par
COPY scenarios/constant_rain.json /app/scenarios/constant_rain.json
COPY scenarios/no_ponding.json /app/scenarios/no_ponding.json
COPY scenarios/variable_rain.json /app/scenarios/variable_rain.json
COPY scenarios/short_intense.json /app/scenarios/short_intense.json
COPY scenarios/multi_burst.json /app/scenarios/multi_burst.json
COPY fortran/gaml_core.f90 /app/fortran/gaml_core.f90

WORKDIR /app
