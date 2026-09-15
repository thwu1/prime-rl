FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 netCDF4==1.7.2

COPY generate_raw_data.py /tmp/generate_raw_data.py
COPY cmor_table.json /app/cmor_table.json

RUN python3 /tmp/generate_raw_data.py && rm /tmp/generate_raw_data.py

RUN python3 -c "import netCDF4; ds=netCDF4.Dataset('/app/raw_data/SynthObs_raw.nc','r'); vs=list(ds.variables.keys()); ds.close(); expected=['time','latitude','longitude','t2m','d2m','mslp','tp_acc','qf_t2m','qf_d2m','qf_mslp','qf_tp']; missing=[v for v in expected if v not in vs]; assert not missing, f'Missing vars: {missing}'"

WORKDIR /app
