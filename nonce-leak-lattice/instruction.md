A custom DSA-like signature scheme is deployed at `/app/`. During each signing operation, a side channel leaks the middle 96 bits (bit positions 80 through 175) of the 256-bit nonce. The group order is the secp256k1 curve order.

The file `/app/challenge.py` describes the signing algorithm and nonce structure. The file `/app/data.json` contains 30 signatures along with the leaked middle nonce bits for each.

Recover the private signing key from the signatures and the partial nonce leakage. Write the key as a lowercase hex string with `0x` prefix to `/app/secret_key.txt`.