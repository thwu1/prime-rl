import random
random.seed(42)
P = 998244353
N = 8
f = [1] + [random.randint(0, P-1) for _ in range(N-1)]

# Read g
with open('/app/output/result.txt') as fp:
    g = [int(l) for l in fp]

# Compute g^3 mod x^8 naively
def poly_mul_naive(a, b, mod, n):
    result = [0]*n
    for i in range(min(len(a), n)):
        for j in range(min(len(b), n-i)):
            result[i+j] = (result[i+j] + a[i]*b[j]) % mod
    return result

g2 = poly_mul_naive(g, g, P, N)
g3 = poly_mul_naive(g2, g, P, N)
print("f   =", f)
print("g   =", g)
print("g^2 =", g2)
print("g^3 =", g3)
print()
print("Coefficient-by-coefficient comparison:")
all_match = True
for i in range(N):
    match = "OK" if f[i] == g3[i] else "MISMATCH"
    if f[i] != g3[i]:
        all_match = False
    print(f"  x^{i}: f={f[i]}, g^3={g3[i]}  {match}")
print()
print("Overall match:", all_match)
