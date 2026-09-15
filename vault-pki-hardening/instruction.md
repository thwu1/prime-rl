A HashiCorp Vault instance at `/app` was configured by a departed colleague. A security audit has revealed multiple critical misconfigurations across the PKI infrastructure, access control policies, authentication methods, secrets management, and audit logging.

The Vault server configuration is at `/app/vault-config.hcl`. Vault data is stored in `/app/vault-data/`. Unseal keys and root token are in `/app/vault-creds/`. The complete remediation requirements are in `/app/remediation-requirements.txt`.

Start the Vault server, diagnose all security and operational deficiencies, remediate them according to the requirements document, and produce a properly hardened Vault deployment. Do not reinitialize Vault; the existing unseal keys and root token must remain valid.

The Vault binary is at `/usr/local/bin/vault`.