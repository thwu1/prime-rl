FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install openpyxl==3.1.5

RUN mkdir -p /app

COPY generate_workbook.py /tmp/generate_workbook.py
RUN python3 /tmp/generate_workbook.py

RUN python3 -c "from openpyxl import load_workbook; wb = load_workbook('/app/group_financials.xlsx'); sheets = wb.sheetnames; print('Verified sheets:', sheets); assert 'Ownership' in sheets, f'Missing Ownership, got {sheets}'; assert 'ExchangeRates' in sheets; assert 'Loans' in sheets; assert 'Intercompany' in sheets; assert 'SubA' in sheets; assert 'SubB' in sheets; assert 'SubC' in sheets; assert 'SubD' in sheets; assert len(list(wb['Ownership'].iter_rows(min_row=2, values_only=True))) >= 4"

RUN rm /tmp/generate_workbook.py

WORKDIR /app
