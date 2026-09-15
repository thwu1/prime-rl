FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output /app/vendor/stdnum

COPY data/iban.dat /app/data/iban.dat
COPY data/batch.json /app/data/batch.json
COPY vendor/stdnum/iban.py /app/vendor/stdnum/iban.py
COPY vendor/stdnum/bic.py /app/vendor/stdnum/bic.py
COPY vendor/stdnum/lei.py /app/vendor/stdnum/lei.py
COPY vendor/stdnum/isin.py /app/vendor/stdnum/isin.py
COPY vendor/stdnum/cusip.py /app/vendor/stdnum/cusip.py
COPY vendor/stdnum/figi.py /app/vendor/stdnum/figi.py
COPY vendor/stdnum/sedol.py /app/vendor/stdnum/sedol.py
COPY vendor/stdnum/iso7064_mod_97_10.py /app/vendor/stdnum/iso7064_mod_97_10.py
COPY vendor/stdnum/luhn.py /app/vendor/stdnum/luhn.py
COPY vendor/stdnum/numdb.py /app/vendor/stdnum/numdb.py
COPY vendor/stdnum/damm.py /app/vendor/stdnum/damm.py
COPY vendor/stdnum/isbn.py /app/vendor/stdnum/isbn.py
COPY vendor/stdnum/verhoeff.py /app/vendor/stdnum/verhoeff.py
COPY vendor/stdnum/util.py /app/vendor/stdnum/util.py
COPY vendor/stdnum/exceptions.py /app/vendor/stdnum/exceptions.py

WORKDIR /app
