A vulnerable x86_64 ELF binary at `/app/challenge` links against `/app/libtarget.so`. The binary has a stack buffer overflow in `pwnme()` but only provides limited overflow space on the stack -- not enough for a full ROP chain.

A heap buffer is allocated at runtime and its address is printed to stdout. Up to 256 bytes of payload can be written there before the stack smash occurs.

`libtarget.so` exports `foothold_function()` (imported by the binary) and also contains a `ret2win()` function that is **not** imported. `ret2win()` requires three `uint64` arguments via `rdi`, `rsi`, `rdx`; when called with the correct values it writes a flag to `/app/flag.txt`.

Binary protections: NX enabled, no PIE, no stack canary, partial RELRO with lazy binding.

Write `/app/exploit.py` that exploits the binary to produce `/app/flag.txt` containing the correct flag.