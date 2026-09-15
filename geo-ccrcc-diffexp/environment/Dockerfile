FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install scipy==1.14.1 numpy==2.1.3 -q

COPY generate_data.py /opt/generate_data.py
RUN python3 /opt/generate_data.py && test -f /opt/geo_data/GSE53757_family.soft && test -f /opt/geo_data/GPL570_annotation.tsv && rm /opt/generate_data.py

COPY buggy_analysis.py /opt/analysis/preliminary_analysis.py
COPY qc_report.txt /opt/analysis/qc_report.txt
RUN python3 /opt/analysis/preliminary_analysis.py

RUN mkdir -p /app/results

WORKDIR /app
