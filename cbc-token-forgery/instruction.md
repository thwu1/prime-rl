Three authentication microservices are running on `localhost` ports `5001`, `5002`, and `5003`. Each encrypts session tokens using a different AES mode of operation. The services are compiled Go binaries with no source code available.

The services expose authentication endpoints but use different transport and encoding:

- **Port 5001**: `GET /api/session` returns raw binary ciphertext (`application/octet-stream`). `POST /api/auth` accepts raw binary token in the request body, returns JSON.
- **Port 5002**: `GET /api/session` returns `{"token": "<hex>"}`. `POST /api/auth` accepts `{"token": "<hex>"}`, returns JSON.
- **Port 5003**: Same JSON API as port 5002, but served over **HTTPS** with a self-signed certificate (cert at `/app/certs/server.crt`).

Each service returns a unique secret flag upon successful admin-level authentication.

A previous security assessor left encrypted notes at `/app/analyst_notes.enc` (encrypted with `openssl enc -aes-256-cbc -pbkdf2`; the passphrase is the SHA256 fingerprint of the port 5003 TLS certificate in uppercase hex without colons).

Perform a black-box cryptographic security assessment of all three services. Determine the AES mode each service uses, attempt to forge admin-privileged tokens to extract flags from each service, and classify each service's exploitability.

The services auto-start on shell login, or run `/app/start_services.sh` manually.

Write your findings to `/app/audit.json` conforming to this schema:

```json
{
  "<port>": {
    "cipher_mode": "<mode>",
    "exploitable": true|false,
    "flag": "<extracted flag or null>"
  }
}
```

Include an entry for each port (5001, 5002, 5003). Set `flag` to the extracted flag string for exploitable services or `null` for non-exploitable ones.

Valid values for `cipher_mode`: `ecb`, `cbc`, `ctr`, `gcm`, `cfb`, `ofb`.