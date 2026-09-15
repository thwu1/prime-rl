FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/specs/test_data

COPY specs/ni_guidance.odt /app/specs/ni_guidance.odt
COPY specs/paye_spec.odt /app/specs/paye_spec.odt
COPY specs/student_loan_spec.txt /app/specs/student_loan_spec.txt
COPY specs/test_data/nic_test_data.xlsx /app/specs/test_data/nic_test_data.xlsx
COPY specs/test_data/nic_directors.xlsx /app/specs/test_data/nic_directors.xlsx
COPY specs/test_data/nic_freeports.xlsx /app/specs/test_data/nic_freeports.xlsx
COPY specs/test_data/uk_tax.xlsx /app/specs/test_data/uk_tax.xlsx
COPY specs/test_data/scottish_tax.xlsx /app/specs/test_data/scottish_tax.xlsx
COPY specs/test_data/welsh_tax.xlsx /app/specs/test_data/welsh_tax.xlsx
COPY specs/test_data/student_loans.ods /app/specs/test_data/student_loans.ods

