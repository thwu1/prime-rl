A set of age v1 encrypted files is located in `/app/corpus/`. An identity key that should decrypt all of them is at `/app/identity.key`. The reference `age` CLI (v1.1.1) and the Python `cryptography` package (v42.0.5) are available.

Some files were produced by faulty implementations containing protocol-level deviations from the age v1 specification. The reference `age` CLI successfully decrypts the conformant files but rejects the non-conformant ones with errors.

Recover the plaintext from every file in `/app/corpus/` that the `age` CLI cannot decrypt. Each plaintext contains a line matching `Token: <value>`. Write only the token values (one per line, sorted lexicographically) to `/app/recovered.txt`.

The age v1 format specification is at https://age-encryption.org/v1 and https://c2sp.org/age.