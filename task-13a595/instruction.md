A C/C++ shared library at `/app/` fails to build from source (FTBFS) as a Debian sid package. The build log at `/app/buildlog.txt` shows the first point of failure — additional defects are latent and will surface only after earlier ones are fixed.

Beyond compilation errors, the library's ABI architecture is fundamentally incomplete. The project declares `-fvisibility=hidden` as its symbol visibility policy but provides no mechanism to export the public API or to apply GNU symbol versioning. A shared library that merely compiles is not shippable — it must present a well-formed ABI surface that downstream consumers and the Debian package toolchain can rely on.

Diagnose and fix every build failure, then design and implement a complete ABI stability architecture so the library satisfies all of the following:

- Builds cleanly with:
  ```
  cd /app && rm -rf build && mkdir build && cd build && \
  cmake .. -DCMAKE_INSTALL_PREFIX=/usr \
           -DCMAKE_C_FLAGS="-Werror=implicit-function-declaration" && \
  make -j$(nproc) && make install DESTDIR=/tmp/verify
  ```

- The SONAME follows Debian shared library policy: it encodes the major ABI version only, not the full release version.

- The four public API functions declared in `api.h` — `netmon_version`, `netmon_check_host`, `netmon_get_local_hostname`, `netmon_print_info` — appear in the dynamic symbol table with the GNU version tag `NETMON_2`. Internal symbols such as `resolve_hostname` must not be exported.

- A downstream C program can compile against the installed headers, link against the installed library, and execute correctly at runtime.

- The `netmon.pc` pkg-config file references the correct include directory for the versioned header path.

- The generated `generated_config.h` contains syntactically valid C version macros.