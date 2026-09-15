"""
Fix the two bugs in the CTR_DRBG implementation at /app/ctr_drbg.py.

Bug 1: In _block_cipher_df, the IV has counter bytes at the wrong end.
  Wrong:  IV = b"\\x00" * (OUTLEN - 4) + struct.pack(">I", counter)
  Right:  IV = struct.pack(">I", counter) + b"\\x00" * (OUTLEN - 4)

Bug 2: In reseed, the state is incorrectly reset to zeros before update.
  Wrong:  self.key = b"\\x00" * KEYLEN; self.v = b"\\x00" * OUTLEN; then update
  Right:  call _ctr_drbg_update directly with current key/v (no reset)

"""

import re


def fix_implementation():
    with open("/app/ctr_drbg.py", "r") as f:
        code = f.read()

    # Fix Bug 1: IV byte order in _block_cipher_df
    # The buggy code has: IV = b"\x00" * (OUTLEN - 4) + struct.pack(">I", counter)
    # Fix to:             IV = struct.pack(">I", counter) + b"\x00" * (OUTLEN - 4)
    code = code.replace(
        'IV = b"\\x00" * (OUTLEN - 4) + struct.pack(">I", counter)',
        'IV = struct.pack(">I", counter) + b"\\x00" * (OUTLEN - 4)',
    )

    # Fix Bug 2: Remove state reset in reseed
    # The buggy code has these lines before _ctr_drbg_update in reseed:
    #   self.key = b"\x00" * KEYLEN
    #   self.v = b"\x00" * OUTLEN
    # We need to remove them while keeping the _ctr_drbg_update call.
    #
    # Find the reseed method and remove the zero-initialization lines
    # Match the pattern: comment + key reset + v reset (in the reseed method)
    code = code.replace(
        '        # Re-initialize state before updating (per Section 10.2.1.4.2 step 3)\n'
        '        self.key = b"\\x00" * KEYLEN\n'
        '        self.v = b"\\x00" * OUTLEN\n'
        '        self.key, self.v = _ctr_drbg_update(seed_material, self.key, self.v)',
        '        self.key, self.v = _ctr_drbg_update(seed_material, self.key, self.v)',
    )

    with open("/app/ctr_drbg.py", "w") as f:
        f.write(code)

    print("Applied 2 fixes to /app/ctr_drbg.py")


if __name__ == "__main__":
    fix_implementation()
