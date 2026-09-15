"""
Quick spot-check of CTR_DRBG against selected CAVP test vectors.
Tests impl_alpha (Python) only. This is NOT a complete validation harness.
"""
import sys
sys.path.insert(0, "/app/impl_alpha")
from ctr_drbg import CTR_DRBG


def main():
    results = []

    # AES-256 no-df, no personalization, no additional input (Count 0)
    drbg = CTR_DRBG(keylen=32, use_df=False)
    e = bytes.fromhex(
        "df5d73faa468649edda33b5cca79b0b05600419ccb7a879d"
        "dfec9db32ee494e5531b51de16a30f769262474c73bec010"
    )
    drbg.instantiate(e, b"")
    drbg.generate(requested_bits=512)
    r, _, _ = drbg.generate(requested_bits=512)
    exp = (
        "d1c07cd95af8a7f11012c84ce48bb8cb87189e99d40fccb1"
        "771c619bdf82ab2280b1dc2f2581f39164f7ac0c510494b3"
        "a43c41b7db17514c87b107ae793e01c5"
    )
    results.append(("no-df / no-pers / no-ai", r.hex() == exp))

    # AES-256 use-df, no personalization, no additional input (Count 0)
    drbg = CTR_DRBG(keylen=32, use_df=True)
    e = bytes.fromhex(
        "36401940fa8b1fba91a1661f211d78a0"
        "b9389a74e5bccfece8d766af1a6d3b14"
    )
    n = bytes.fromhex("496f25b0f1301b4f501be30380a137eb")
    drbg.instantiate(e, n)
    drbg.generate(requested_bits=512)
    r, _, _ = drbg.generate(requested_bits=512)
    exp = (
        "5862eb38bd558dd978a696e6df164782ddd887e7e9a6c9f3"
        "f1fbafb78941b535a64912dfd224c6dc7454e5250b3d9716"
        "5e16260c2faf1cc7735cb75fb4f07e1d"
    )
    results.append(("use-df / no-pers / no-ai", r.hex() == exp))

    for name, passed in results:
        print(f"  {'PASS' if passed else 'FAIL'} - {name}")

    total = len(results)
    ok = sum(1 for _, p in results if p)
    print(f"\n{ok}/{total} spot checks passed")
    if ok < total:
        print("Implementation has defects. See /app/vectors/ for reference data.")
        sys.exit(1)


if __name__ == "__main__":
    main()
