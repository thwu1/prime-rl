A simplified post-quantum signature scheme called **Vinaigrette** has been deployed. It is based on the Unbalanced Oil and Vinegar (UOV) construction but omits the emulsifier matrices used in the full MAYO scheme. Your task is to forge a valid signature.

## Scheme Overview

Vinaigrette uses a multivariate quadratic (MQ) mapping P: F_q^n -> F_q^m defined by m quadratic polynomials over the finite field F_q. Each polynomial p_j(x) = x^T P_j x where P_j is an n x n matrix over F_q.

There exists a secret o-dimensional linear subspace O (the "oil space") on which all polynomials vanish: p_j(o) = 0 for every o in O and every j.

Signing uses a "whipped up" construction: the signature s = (s_1, ..., s_k) consists of k vectors in F_q^n, and verification checks:

    sum_{i=1}^{k} p_j(s_i) = H(lambda)_j    (mod q)    for j = 1, ..., m

where H is derived from SHAKE256 applied to the message lambda.

## Parameters

The instance at `/app/params.json` uses: q=31, n=20, m=16, o=4, k=4.

## Public Key Format

`/app/public_key.txt` contains m=16 matrices, each 20x20 over F_31 (entries 0-30). Each matrix is given row-by-row as space-separated integers. Matrices are separated by a blank line.

The j-th polynomial is evaluated as: p_j(x) = sum over all i,r in {0..n-1} of P_j[i][r] * x[i] * x[r], reduced mod q.

## Hash Construction

The hash H(lambda) is computed as follows:
1. Compute SHAKE256 of the message bytes (UTF-8 encoded).
2. Take the first ceil(5 * m / 8) = 10 bytes of XOF output.
3. Convert to a bitstring (MSB first per byte).
4. Extract m consecutive 5-bit chunks (bits 0..4 for H_0, bits 5..9 for H_1, etc.).
5. Each 5-bit value is reduced mod q to obtain H_j in F_q.

The precomputed hash target is also at `/app/hash_target.txt` for convenience.

## Message

    Mayonnaise is not an instrument

## Task

Forge a valid signature for the message above and write it to `/app/signature.txt`. The signature should be a single line of k*n = 80 space-separated integers, each in {0, ..., 30}, representing the concatenation (s_1, s_2, s_3, s_4).