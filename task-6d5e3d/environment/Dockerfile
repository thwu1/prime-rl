
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip python3-dev build-essential \
    libproj-dev proj-data proj-bin \
    libgeos-dev \
    libsqlite3-dev \
    curl jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install Babel==2.16.0 click==8.1.8 filelock==3.16.1 Flask==3.1.0 \
    Flask-Cors==5.0.1 jinja2==3.1.5 jsonschema==4.23.0 pydantic==2.10.6 \
    pygeofilter==0.2.4 pygeoif==1.5.1 pyproj==3.7.1 \
    python-dateutil==2.9.0.post0 pytz==2024.2 PyYAML==6.0.2 \
    requests==2.32.3 shapely==2.0.7 SQLAlchemy==2.0.37 tinydb==4.8.2

RUN pip3 install pygeoapi==0.23.4 --no-deps

RUN mkdir -p /app/data /app/plugins

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

COPY broken_provider.py /app/plugins/station_provider.py
COPY broken_config.yml /app/config.yml

WORKDIR /app
