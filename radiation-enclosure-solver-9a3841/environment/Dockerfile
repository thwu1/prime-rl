FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip nodejs sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/catalog /app/enclosures

COPY vfcalc.js /app/catalog/vfcalc.js
COPY formulas.json /app/catalog/formulas.json
COPY box_furnace.json /app/enclosures/box_furnace.json
COPY long_duct.json /app/enclosures/long_duct.json
COPY cylinder_heater.json /app/enclosures/cylinder_heater.json
COPY spheres_radiator.json /app/enclosures/spheres_radiator.json
COPY blackbody_cube.json /app/enclosures/blackbody_cube.json

WORKDIR /app
