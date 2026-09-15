from secret import config
from Crypto.PublicKey import RSA
from Crypto.Util.number import bytes_to_long, isPrime


class LCG:
    lcg_m = config.m    # multiplier
    lcg_c = config.c    # increment
    lcg_n = config.n    # modulus

    def __init__(self, lcg_s):
        self.state = lcg_s

    def next(self):
        self.state = (self.state * self.lcg_m + self.lcg_c) % self.lcg_n
        return self.state


NUM_PRIMES = 8
PRIME_BITS = 512
RSA_E = 65537

# Known seed
SEED = 271828182845904523536028747135266249775724709369995

if __name__ == '__main__':
    lcg = LCG(SEED)
    primes = []

    dump_file = open("dump.txt", "w")
    dump_count = 0

    while len(primes) < NUM_PRIMES:
        candidate = lcg.next()
        if dump_count < 6:
            dump_file.write(str(candidate) + '\n')
            dump_count += 1
        if isPrime(candidate) and candidate.bit_length() == PRIME_BITS:
            primes.append(candidate)

    dump_file.close()

    # Build RSA public key from the primes
    n = 1
    for p in primes:
        n *= p

    # Compute Euler's totient
    phi = 1
    for p in primes:
        phi *= (p - 1)

    d = pow(RSA_E, -1, phi)

    # Encrypt flag
    flag_int = bytes_to_long(config.flag)
    assert flag_int < n
    ct = pow(flag_int, RSA_E, n)

    # Save ciphertext as hex
    with open("flag.enc", "w") as f:
        f.write(hex(ct))

    # Save public key
    rsa = RSA.construct((n, RSA_E))
    with open("public.pem", "w") as f:
        f.write(rsa.exportKey().decode())
