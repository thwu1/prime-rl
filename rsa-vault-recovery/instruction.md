A secure vault at `/app/` protects a master secret using Shamir's (4,6) Secret Sharing Scheme. Each of the 6 shares was encrypted with a different party's RSA public key (textbook RSA, no padding).

The vault operator collected public keys from parties through different infrastructure channels and never audited key quality. As a result, the keys and encrypted shares are distributed across multiple storage formats:

- **Parties 1-3**: X.509 PEM certificates in `/app/pki/`
- **Party 4**: DER-encoded SubjectPublicKeyInfo in `/app/keys/party4_pub.der`
- **Party 5**: Public key and encrypted share were captured in a network transfer recorded at `/app/captures/share_transfer.pcap`
- **Party 6**: PGP public key export at `/app/pgp/party6.asc`

Encrypted share ciphertexts (except party 5's, which is in the pcap) are in `/app/shares/`. The vault manifest at `/app/vault_manifest.json` contains the Shamir scheme parameters and file locations. A reference protocol implementation is at `/app/vault_protocol.py`.

Your task: extract RSA public key parameters from each format using appropriate tools, identify and exploit cryptographic weaknesses in at least 4 of the 6 RSA keys to recover their private keys, decrypt the corresponding shares, and reconstruct the master secret via Lagrange interpolation.

Write the recovered master secret as a lowercase hex string (no `0x` prefix) to `/app/secret.txt`.