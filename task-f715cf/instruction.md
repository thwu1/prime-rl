A simplified post-quantum signature scheme called **Vinaigrette** is implemented in `/app/vinaigrette.py`. It is based on the Unbalanced Oil and Vinegar (UOV) construction but omits the emulsifier matrices used in the full MAYO scheme. The scheme operates over F_31 with parameters `(q, n, m, o, k) = (31, 14, 10, 4, 3)`.

The public key is at `/app/public_key.txt` (10 upper-triangular 14x14 matrices over F_31, stored row-by-row starting from the diagonal, matrices separated by blank lines).

The message to sign is: `Forge this signature to prove you broke Vinaigrette`

A valid signature `s = (s_1, s_2, s_3)` where each `s_i` is a vector in F_31^14 must satisfy `P*(s) = H(message)`, where `P*` is the whipped-up MQ mapping and `H` uses SHAKE256 (see `/app/vinaigrette.py` for exact definitions).

Write a valid signature as 42 space-separated integers (each in 0..30) to `/app/signature.txt`.