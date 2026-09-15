#!/bin/bash
set -e

OPENSSL=/usr/local/bin/openssl
PKI=/app/pki

# Create directory structure
for CA in root-ca intermediate-ca; do
    mkdir -p "$PKI/$CA"/{private,certs,crl,newcerts,csr}
    chmod 700 "$PKI/$CA/private"
done
mkdir -p "$PKI/certs"

# Initialize CA databases
for CA in root-ca intermediate-ca; do
    touch "$PKI/$CA/index.txt"
    echo 'unique_subject = no' > "$PKI/$CA/index.txt.attr"
done
echo '1000' > "$PKI/root-ca/serial"
echo '1000' > "$PKI/root-ca/crlnumber"
echo '2000' > "$PKI/intermediate-ca/serial"
echo '2000' > "$PKI/intermediate-ca/crlnumber"

# -----------------------------------------------------------------------
# Root CA OpenSSL configuration (config itself is correct)
# -----------------------------------------------------------------------
cat > "$PKI/root-ca/openssl.cnf" << 'ROOTCFG'
[ca]
default_ca = CA_default

[CA_default]
dir               = /app/pki/root-ca
certs             = $dir/certs
crl_dir           = $dir/crl
new_certs_dir     = $dir/newcerts
database          = $dir/index.txt
serial            = $dir/serial
private_key       = $dir/private/root-ca.key
certificate       = $dir/certs/root-ca.crt
crlnumber         = $dir/crlnumber
crl               = $dir/crl/root-ca.crl
crl_extensions    = crl_ext
default_crl_days  = 30
default_md        = sha512
default_days      = 3650
preserve          = no
policy            = policy_strict

[policy_strict]
countryName             = match
stateOrProvinceName     = match
organizationName        = match
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional

[req]
distinguished_name = req_distinguished_name
string_mask        = utf8only
default_md         = sha512
x509_extensions    = v3_ca
prompt             = no

[req_distinguished_name]
C  = US
ST = Virginia
L  = Arlington
O  = PQC Corp
OU = PKI Operations
CN = PQC Root CA

[v3_ca]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical, CA:TRUE
keyUsage               = critical, digitalSignature, cRLSign, keyCertSign

[v3_intermediate_ca]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical, CA:TRUE, pathlen:0
keyUsage               = critical, digitalSignature, cRLSign, keyCertSign

[crl_ext]
authorityKeyIdentifier = keyid:always
ROOTCFG

# -----------------------------------------------------------------------
# Intermediate CA OpenSSL configuration (WITH DELIBERATE DEFECTS)
# DEFECT A: server_cert keyUsage includes keyEncipherment (invalid for PQC sig keys)
# DEFECT B: server_alt_names missing wildcard DNS and IP SAN
# DEFECT C: client_cert extendedKeyUsage is serverAuth (should be clientAuth, emailProtection)
# -----------------------------------------------------------------------
cat > "$PKI/intermediate-ca/openssl.cnf" << 'INTCFG'
[ca]
default_ca = CA_default

[CA_default]
dir               = /app/pki/intermediate-ca
certs             = $dir/certs
crl_dir           = $dir/crl
new_certs_dir     = $dir/newcerts
database          = $dir/index.txt
serial            = $dir/serial
private_key       = $dir/private/intermediate-ca.key
certificate       = $dir/certs/intermediate-ca.crt
crlnumber         = $dir/crlnumber
crl               = $dir/crl/intermediate-ca.crl
crl_extensions    = crl_ext
default_crl_days  = 30
default_md        = sha512
default_days      = 730
preserve          = no
policy            = policy_loose

[policy_loose]
countryName             = optional
stateOrProvinceName     = optional
localityName            = optional
organizationName        = optional
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional

[req]
distinguished_name = req_distinguished_name
string_mask        = utf8only
default_md         = sha512
prompt             = no

[req_distinguished_name]
C  = US
ST = Virginia
L  = Arlington
O  = PQC Corp
OU = PKI Operations
CN = PQC Intermediate CA

[server_cert]
basicConstraints       = CA:FALSE
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
keyUsage               = critical, digitalSignature, keyEncipherment
extendedKeyUsage       = serverAuth
subjectAltName         = @server_alt_names

[server_alt_names]
DNS.1 = server.pqc.lab

[client_cert]
basicConstraints       = CA:FALSE
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
keyUsage               = critical, digitalSignature
extendedKeyUsage       = serverAuth

[ocsp_cert]
basicConstraints       = CA:FALSE
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
keyUsage               = critical, digitalSignature
extendedKeyUsage       = critical, OCSPSigning

[crl_ext]
authorityKeyIdentifier = keyid:always
INTCFG

# -----------------------------------------------------------------------
# DEFECT 1: Root CA uses ML-DSA-65 instead of ML-DSA-87
# ML-DSA-65 is FIPS 204 Level 3 but CNSA 2.0 mandates Level 5 (ML-DSA-87)
# -----------------------------------------------------------------------
$OPENSSL genpkey -algorithm mldsa65 -out "$PKI/root-ca/private/root-ca.key"
chmod 400 "$PKI/root-ca/private/root-ca.key"

$OPENSSL req -config "$PKI/root-ca/openssl.cnf" \
    -new -x509 \
    -key "$PKI/root-ca/private/root-ca.key" \
    -extensions v3_ca \
    -days 3650 \
    -out "$PKI/root-ca/certs/root-ca.crt"

# -----------------------------------------------------------------------
# Intermediate CA key is ML-DSA-87 (correct), but its cert will be
# signed by Root CA using ML-DSA-65 (cascading from Defect 1)
# -----------------------------------------------------------------------
$OPENSSL genpkey -algorithm mldsa87 -out "$PKI/intermediate-ca/private/intermediate-ca.key"
chmod 400 "$PKI/intermediate-ca/private/intermediate-ca.key"

$OPENSSL req -config "$PKI/intermediate-ca/openssl.cnf" \
    -new \
    -key "$PKI/intermediate-ca/private/intermediate-ca.key" \
    -out "$PKI/intermediate-ca/csr/intermediate-ca.csr"

# DEFECT 2 (cascade): Intermediate CA cert signed with ML-DSA-65
$OPENSSL ca -config "$PKI/root-ca/openssl.cnf" \
    -extensions v3_intermediate_ca \
    -days 1825 \
    -notext -batch \
    -in "$PKI/intermediate-ca/csr/intermediate-ca.csr" \
    -out "$PKI/intermediate-ca/certs/intermediate-ca.crt"

# -----------------------------------------------------------------------
# Server certificate (ML-DSA-87 key, but defective extensions from config)
# -----------------------------------------------------------------------
$OPENSSL genpkey -algorithm mldsa87 -out "$PKI/intermediate-ca/private/server.key"
chmod 400 "$PKI/intermediate-ca/private/server.key"

$OPENSSL req -config "$PKI/intermediate-ca/openssl.cnf" \
    -new \
    -key "$PKI/intermediate-ca/private/server.key" \
    -subj "/C=US/ST=Virginia/L=Arlington/O=PQC Corp/OU=Web Services/CN=server.pqc.lab" \
    -out "$PKI/intermediate-ca/csr/server.csr"

# DEFECT 3+4: keyEncipherment in keyUsage, missing SANs
$OPENSSL ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -extensions server_cert \
    -days 365 \
    -notext -batch \
    -in "$PKI/intermediate-ca/csr/server.csr" \
    -out "$PKI/intermediate-ca/certs/server.crt"

# -----------------------------------------------------------------------
# Client certificate (ML-DSA-87 key, but wrong EKU from config)
# -----------------------------------------------------------------------
$OPENSSL genpkey -algorithm mldsa87 -out "$PKI/intermediate-ca/private/client.key"
chmod 400 "$PKI/intermediate-ca/private/client.key"

$OPENSSL req -config "$PKI/intermediate-ca/openssl.cnf" \
    -new \
    -key "$PKI/intermediate-ca/private/client.key" \
    -subj "/C=US/ST=Virginia/L=Arlington/O=PQC Corp/OU=Users/CN=client@pqc.lab" \
    -out "$PKI/intermediate-ca/csr/client.csr"

# DEFECT 5: extendedKeyUsage = serverAuth (wrong for client cert)
$OPENSSL ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -extensions client_cert \
    -days 365 \
    -notext -batch \
    -in "$PKI/intermediate-ca/csr/client.csr" \
    -out "$PKI/intermediate-ca/certs/client.crt"

# -----------------------------------------------------------------------
# DEFECT 6: No OCSP signing certificate created
# DEFECT 7: Empty CRL (no revocations performed)
# -----------------------------------------------------------------------
$OPENSSL ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -gencrl \
    -out "$PKI/intermediate-ca/crl/intermediate-ca.crl"

# DEFECT 8: No CA chain bundle created at /app/pki/certs/ca-chain.crt
# DEFECT 9: No TLS test performed

echo "Setup complete: broken PKI deployed at $PKI"
