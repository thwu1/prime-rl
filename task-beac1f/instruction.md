Implement the `pledge()` function in `/app/pledge.c` to restrict which system calls the calling process may execute, inspired by OpenBSD's `pledge(2)`. The API is declared in `/app/pledge.h` and the build system and test harness are provided in `/app/`.

The function accepts a space-separated string of promise categories. Once installed, only syscalls belonging to the pledged categories may execute -- any disallowed syscall must terminate the process immediately. The six supported categories are `stdio`, `rpath`, `wpath`, `cpath`, `inet`, and `proc`, with per-category syscall scopes as documented in the header.

Key behavioral requirements:
- `rpath` permits `openat` only for read-only access; write-mode opens under `rpath` alone must be denied
- When both `rpath` and `wpath` are pledged, `openat` is unrestricted
- `inet` permits socket creation only for IPv4 and IPv6 address families; other socket domains must be denied
- Passing `NULL` applies no restrictions; passing `""` restricts everything except process exit

Build with `make -C /app` and verify with `/app/test_harness`.