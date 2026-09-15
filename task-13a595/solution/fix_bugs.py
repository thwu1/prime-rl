#!/usr/bin/env python3
"""Fix all defects and create ABI architecture for the netmon library.

Build-time bugs:
  Bug 1: CMake duplicate imported target (FindIceCompat.cmake)
  Bug 2: Python codegen format specifier type error (codegen.py)
  Bug 3: Missing C header for gethostname (netmon.c)
  Bug 4: Wrong include path in pkg-config template (netmon.pc.in)

ABI-level bugs:
  Bug 5: Swapped VERSION/SOVERSION properties (CMakeLists.txt)

ABI architecture (design and create from scratch):
  Bug 6: No symbol export mechanism despite -fvisibility=hidden
  Bug 7: No GNU symbol versioning
"""

import sys


def read_file(path):
    with open(path, 'r') as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)


def patch(path, old, new, desc):
    """Replace old with new in file. Abort if old string is not found."""
    content = read_file(path)
    if old not in content:
        print(f"FATAL: target string not found for [{desc}] in {path}",
              file=sys.stderr)
        sys.exit(1)
    content = content.replace(old, new, 1)
    write_file(path, content)
    print(f"  OK: {desc}")


# ---- Bug 1: CMake duplicate imported target ----
print("Bug 1: CMake imported target guard")
patch('/app/cmake/FindIceCompat.cmake',
      'add_library(IceCompat::core INTERFACE IMPORTED)\n'
      'set_target_properties(IceCompat::core PROPERTIES\n'
      '  INTERFACE_INCLUDE_DIRECTORIES "${ICECOMPAT_INCLUDE_DIR}"\n'
      ')',
      'if(NOT TARGET IceCompat::core)\n'
      '  add_library(IceCompat::core INTERFACE IMPORTED)\n'
      '  set_target_properties(IceCompat::core PROPERTIES\n'
      '    INTERFACE_INCLUDE_DIRECTORIES "${ICECOMPAT_INCLUDE_DIR}"\n'
      '  )\n'
      'endif()',
      'guard IceCompat::core target creation')

# ---- Bug 2: codegen.py format specifier ----
print("Bug 2: codegen.py int conversion")
patch('/app/tools/codegen.py',
      '    major, minor, patch = parts',
      '    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])',
      'convert version components to int')

# ---- Bug 3: missing unistd.h ----
print("Bug 3: missing <unistd.h>")
patch('/app/src/netmon.c',
      '#include <string.h>',
      '#include <string.h>\n#include <unistd.h>',
      'add #include <unistd.h> for gethostname')

# ---- Bug 4: pkg-config include path ----
print("Bug 4: pkg-config Cflags path")
patch('/app/netmon.pc.in',
      'Cflags: -I${includedir}/netmon',
      'Cflags: -I${includedir}/netmon-v2',
      'fix Cflags to reference netmon-v2')

# ---- Bug 5: swapped VERSION / SOVERSION ----
print("Bug 5: VERSION/SOVERSION swap")
patch('/app/CMakeLists.txt',
      '  VERSION 2\n  SOVERSION 2.0.0',
      '  VERSION 2.0.0\n  SOVERSION 2',
      'correct VERSION=2.0.0, SOVERSION=2')

# ---- Create export header and annotate public API ----
print("Creating visibility export header")
write_file('/app/include/netmon-v2/netmon_export.h', '''\
#ifndef NETMON_EXPORT_H
#define NETMON_EXPORT_H

#if defined(__GNUC__) && __GNUC__ >= 4
  #define NETMON_EXPORT __attribute__((visibility("default")))
#else
  #define NETMON_EXPORT
#endif

#endif /* NETMON_EXPORT_H */
''')
print("  OK: created netmon_export.h")

print("Annotating public API with NETMON_EXPORT")
patch('/app/include/netmon-v2/api.h',
      '#include <stddef.h>',
      '#include <stddef.h>\n#include "netmon_export.h"',
      'include netmon_export.h in api.h')

for old_decl, new_decl in [
    ('const char* netmon_version(void);',
     'NETMON_EXPORT const char* netmon_version(void);'),
    ('int netmon_check_host(const char *hostname);',
     'NETMON_EXPORT int netmon_check_host(const char *hostname);'),
    ('int netmon_get_local_hostname(char *buf, size_t len);',
     'NETMON_EXPORT int netmon_get_local_hostname(char *buf, size_t len);'),
    ('void netmon_print_info(void);',
     'NETMON_EXPORT void netmon_print_info(void);'),
]:
    fname = old_decl.split('(')[0].split()[-1]
    patch('/app/include/netmon-v2/api.h', old_decl, new_decl,
          f'NETMON_EXPORT {fname}')

# ---- Create GNU linker version script ----
print("Creating version script")
write_file('/app/netmon.map', '''\
NETMON_2 {
    global:
        netmon_version;
        netmon_check_host;
        netmon_get_local_hostname;
        netmon_print_info;
    local:
        *;
};
''')
print("  OK: created netmon.map")

# ---- Integrate version script into CMake build ----
# Append to end of CMakeLists.txt (avoids fragile string-matching insertions)
print("Integrating version script into CMakeLists.txt")
cmake_path = '/app/CMakeLists.txt'
cmake = read_file(cmake_path)
cmake += '''
# GNU symbol versioning via linker version script
target_link_options(netmon PRIVATE
  "-Wl,--version-script=${CMAKE_SOURCE_DIR}/netmon.map")
set_target_properties(netmon PROPERTIES
  LINK_DEPENDS "${CMAKE_SOURCE_DIR}/netmon.map")
'''
write_file(cmake_path, cmake)
print("  OK: appended version script link options to CMakeLists.txt")

print("\nAll defects fixed and ABI architecture created.")
