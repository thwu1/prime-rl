A vulnerable x86-64 ELF binary `/app/gauntlet` and its companion shared library `/app/libgauntlet.so` require exploitation via Return-Oriented Programming.

The binary allocates a heap buffer (printing its address), then reads user input in two stages: 256 bytes to the heap buffer, and 64 bytes into a 32-byte stack-local buffer. NX is enabled; PIE, stack canaries, and full RELRO are disabled.

The shared library exports `foothold_function()` (imported by the binary, has a PLT entry) and `ret2win(uint64_t a, uint64_t b, uint64_t c)` (NOT imported by the binary — no PLT entry exists for it). Calling `ret2win` with `rdi=0xdeadbeefdeadbeef`, `rsi=0xcafebabecafebabe`, `rdx=0xd00df00dd00df00d` prints the contents of `/app/flag.txt`.

Create `/app/exploit.py` — a Python script that programmatically exploits the binary to print the flag to stdout. The exploit must work regardless of the flag file's contents, as the flag is regenerated at verification time.