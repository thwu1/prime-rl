FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip git && rm -rf /var/lib/apt/lists/*

RUN pip3 install dbt-duckdb==1.9.1

COPY dbt_project.yml /app/dbt_project/dbt_project.yml
COPY requirements.md /app/dbt_project/requirements.md
COPY seeds/ /app/dbt_project/seeds/
COPY models/ /app/dbt_project/models/
COPY macros/ /app/dbt_project/macros/

RUN mkdir -p /etc/dbt_profiles
COPY profiles.yml /etc/dbt_profiles/profiles.yml
ENV DBT_PROFILES_DIR=/etc/dbt_profiles

WORKDIR /app
