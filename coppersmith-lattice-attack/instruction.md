The file `/app/challenge/challenge.json` contains three RSA attack instances that must be solved using variants of Coppersmith's lattice-based method (LLL reduction applied to carefully constructed polynomial lattices).

**Part 1 -- Partial Factoring:** You are given a 1024-bit RSA modulus `N = p*q` and the value `p_high_bits`, which is `p` with its bottom 86 bits zeroed. Use Coppersmith's method to recover the full factorization of `N`.

**Part 2 -- Stereotyped Message Attack:** A base-35 encoded message (digits `0-9`, letters `a-y` where `a=10,...,y=34`) was encrypted with textbook RSA using `e=3`. You know the first 18 characters of the 28-character message. Recover the unknown 10-character suffix.

**Part 3 -- Hastad Broadcast with Linear Padding:** The same 300-bit message `m` was encrypted for three recipients using `e=3` with individual linear padding: `c_i = (m + b_i)^3 mod N_i`. The padding values `b_i` are known. Recover `m`.

Write your results to `/app/answer.json`:
```json
{
  "part1_p": "<decimal string>",
  "part1_q": "<decimal string>",
  "part2_suffix": "<10-char base-35 string>",
  "part3_message": "<decimal string>"
}
```