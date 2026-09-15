from secret import config
from prng import HardenedPRNG
from Crypto.Util.number import isPrime, bytes_to_long
from Crypto.PublicKey import RSA


NUM_PRIMES = 8
PRIME_BITS = 512
RSA_E = 65537

# Known seed (public)
SEED = 271828182845904523536028747135266249775724709369995


def generate_keypair():
    prng = HardenedPRNG(
        seed=SEED,
        multiplier=config.multiplier,
        increment=config.increment,
        modulus=config.modulus,
        whiten_rounds=config.whiten_rounds,
    )

    primes = []
    while len(primes) < NUM_PRIMES:
        candidate = prng.generate()
        if isPrime(candidate) and candidate.bit_length() == PRIME_BITS:
            primes.append(candidate)

    n = 1
    for p in primes:
        n *= p

    phi = 1
    for p in primes:
        phi *= (p - 1)

    d = pow(RSA_E, -1, phi)
    return RSA.construct((n, RSA_E, d))


if __name__ == '__main__':
    key = generate_keypair()

    with open("pubkey.der", "wb") as f:
        f.write(key.publickey().export_key(format='DER'))

    ct = pow(bytes_to_long(config.plaintext), RSA_E, key.n)
    with open("intercepted.enc", "w") as f:
        f.write(hex(ct))
