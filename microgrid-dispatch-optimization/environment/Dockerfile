FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

RUN python3 -c "import json; d=json.load(open('/app/data/microgrid_stochastic.json')); assert len(d['scenarios'])==5; assert all(len(s['time_series'])==48 for s in d['scenarios']); assert 'electrolyzer_pwl_input_kw' in d['system']; assert 'risk_parameters' in d; print('Stochastic data verification OK')"

WORKDIR /app
