A partially configured two-tier PKI infrastructure exists at `/app/pki/`. The OpenSSL configuration files for the Root CA (`/app/pki/root-ca/openssl.cnf`) and the Intermediate CA (`/app/pki/intermediate-ca/openssl.cnf`) each contain multiple errors that will cause certificate operations to fail or produce non-compliant artifacts.

The Root CA's EC P-384 private key has already been generated at `/app/pki/root-ca/private/root-ca.key`. Certificate database files (`index.txt`, `serial`, `crlnumber`) are initialized for both CAs.

Deployment-specific parameters are in `/app/pki/deploy_params.json`. The full requirements specification at `/app/pki/requirements.md` references these parameters — every certificate's Organizational Unit must incorporate the deployment audit stamp, and the server certificate SAN must use the deployment-specified IP address.

Diagnose and fix all configuration errors, then build the complete PKI:

- Generate the Root CA self-signed certificate with correct extensions (CA:TRUE, keyCertSign, cRLSign, strong digest)
- Build a complete Intermediate CA: generate an EC P-384 key, create a CSR, sign it with the Root CA, and assemble the chain file
- Issue a server certificate for `web.securecorp.lab` with DNS and IP SANs per the requirements spec, and `serverAuth` EKU
- Issue a client certificate for Alice Chen (`alice@securecorp.lab`) with `clientAuth` and `emailProtection` EKUs, and an email SAN
- Revoke the client certificate with reason `keyCompromise` and generate a CRL
- Enforce file permissions: private keys `0400`, certificates `0444`
- Ensure all certificates carry the correct deployment-stamped OU fields

Full specifications including exact file paths are in `/app/pki/requirements.md`.