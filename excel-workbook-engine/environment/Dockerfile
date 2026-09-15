FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install openpyxl==3.1.5

RUN mkdir -p /data /app/output

COPY data/transactions.csv /data/transactions.csv
COPY data/products.csv /data/products.csv
COPY data/employees.csv /data/employees.csv
COPY data/budgets.csv /data/budgets.csv
COPY build_workbook.py /app/build_workbook.py

WORKDIR /app
