#!/usr/bin/env python3
"""
Fix all issues in the netdaemon project, create version scripts and cmake config package.

This solution evaluates the conflicting MIGRATION_PLAN.md against the actual source code
and ABI_POLICY.md, resolving contradictions in favor of the code and policy.
"""

import os
import re
import subprocess
import shutil

APP = "/app"


def read(path):
    with open(os.path.join(APP, path)) as f:
        return f.read()


def write(path, content):
    full = os.path.join(APP, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)


def main():
    # -----------------------------------------------------------------------
    # 1. Rewrite top-level CMakeLists.txt
    #    EVALUATION: Migration notes say libevent is needed — WRONG.
    #    ndcore.c doesn't use any libevent APIs. Remove find_package(LibEvent).
    #    EVALUATION: Migration notes say SOVERSION stays at 2 — WRONG.
    #    ABI_POLICY.md says SOVERSION = major version = 3.
    #    FIX: Move include(GNUInstallDirs) before first CMAKE_INSTALL_* use.
    #    CREATE: Add cmake config package support from scratch.
    # -----------------------------------------------------------------------
    write("CMakeLists.txt", """\
cmake_minimum_required(VERSION 3.14)
project(netdaemon VERSION 3.0.0 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

# Dependencies — only OpenSSL is actually used (libevent is NOT used despite
# what MIGRATION_PLAN.md claims; the code has no libevent API calls)
find_package(OpenSSL REQUIRED)

# Build options
option(BUILD_SHARED_LIBS "Build shared libraries" ON)
option(ENABLE_SERVER "Build server daemon" ON)
option(ENABLE_CLIENT "Build client tools" ON)

# Library versioning — SOVERSION = major version per ABI_POLICY.md
set(ND_SOVERSION 3)
set(ND_VERSION ${PROJECT_VERSION})

# Build targets
add_subdirectory(src/core)
add_subdirectory(src/crypto)

if(ENABLE_CLIENT)
  add_subdirectory(src/client)
endif()

if(ENABLE_SERVER)
  add_subdirectory(src/server)
endif()

# Install pkg-config file
configure_file(pkg/netdaemon.pc.in ${CMAKE_CURRENT_BINARY_DIR}/netdaemon.pc @ONLY)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/netdaemon.pc
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/pkgconfig)

# Install systemd service file
install(FILES pkg/netdaemon.service
  DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/systemd/system)

# CMake config-mode package (created from scratch — no prior template exists)
configure_package_config_file(
  cmake/netdaemonConfig.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/netdaemonConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/netdaemon
)

write_basic_package_version_file(
  ${CMAKE_CURRENT_BINARY_DIR}/netdaemonConfigVersion.cmake
  VERSION ${PROJECT_VERSION}
  COMPATIBILITY SameMajorVersion
)

install(FILES
  ${CMAKE_CURRENT_BINARY_DIR}/netdaemonConfig.cmake
  ${CMAKE_CURRENT_BINARY_DIR}/netdaemonConfigVersion.cmake
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/netdaemon
)

install(EXPORT netdaemonTargets
  NAMESPACE netdaemon::
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/netdaemon
)
""")

    # -----------------------------------------------------------------------
    # 2. Create cmake config template (from scratch — no prior template)
    # -----------------------------------------------------------------------
    write("cmake/netdaemonConfig.cmake.in", """\
@PACKAGE_INIT@

include(CMakeFindDependencyMacro)
find_dependency(OpenSSL)

include("${CMAKE_CURRENT_LIST_DIR}/netdaemonTargets.cmake")

check_required_components(netdaemon)
""")

    # -----------------------------------------------------------------------
    # 3. Create version scripts per ABI_POLICY.md symbol export policy
    #    EVALUATE: identify public symbols from headers
    #    CREATE: write GNU ld version scripts from scratch
    # -----------------------------------------------------------------------

    # ndcore public API (from src/core/ndcore.h):
    #   nd_config_init, nd_config_free, nd_config_load, nd_log, nd_version_string
    write("src/core/libndcore.map", """\
NDCORE_3.0 {
  global:
    nd_config_init;
    nd_config_free;
    nd_config_load;
    nd_log;
    nd_version_string;
  local:
    *;
};
""")

    # ndcrypto public API (from src/crypto/ndcrypto.h):
    #   nd_hash_password, nd_verify_password, nd_generate_token
    write("src/crypto/libndcrypto.map", """\
NDCRYPTO_3.0 {
  global:
    nd_hash_password;
    nd_verify_password;
    nd_generate_token;
  local:
    *;
};
""")

    # -----------------------------------------------------------------------
    # 4. Fix src/core/CMakeLists.txt
    #    - Remove target_link_libraries(ndcore PRIVATE event) — libevent not used
    #    - Add EXPORT netdaemonTargets
    #    - Add version script integration
    # -----------------------------------------------------------------------
    write("src/core/CMakeLists.txt", """\
add_library(ndcore
  ndcore.c
  ndcore.h
)

target_include_directories(ndcore PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/netdaemon>
)

set_target_properties(ndcore PROPERTIES
  VERSION ${ND_VERSION}
  SOVERSION ${ND_SOVERSION}
  OUTPUT_NAME ndcore
  LINK_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/libndcore.map"
)

target_link_options(ndcore PRIVATE
  "LINKER:--version-script=${CMAKE_CURRENT_SOURCE_DIR}/libndcore.map"
)

install(TARGETS ndcore
  EXPORT netdaemonTargets
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install(FILES ndcore.h
  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/netdaemon
)
""")

    # -----------------------------------------------------------------------
    # 5. Fix src/crypto/CMakeLists.txt
    #    EVALUATION: Migration notes say ndcrypto is standalone — WRONG.
    #    ndcrypto.c includes "../core/ndcore.h" and calls nd_log().
    #    Keep the PUBLIC ndcore dependency.
    #    - Add EXPORT netdaemonTargets
    #    - Add version script integration
    # -----------------------------------------------------------------------
    write("src/crypto/CMakeLists.txt", """\
add_library(ndcrypto
  ndcrypto.c
  ndcrypto.h
)

target_include_directories(ndcrypto PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/netdaemon>
)

target_link_libraries(ndcrypto
  PRIVATE OpenSSL::Crypto
  PUBLIC ndcore
)

set_target_properties(ndcrypto PROPERTIES
  VERSION ${ND_VERSION}
  SOVERSION ${ND_SOVERSION}
  OUTPUT_NAME ndcrypto
  LINK_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/libndcrypto.map"
)

target_link_options(ndcrypto PRIVATE
  "LINKER:--version-script=${CMAKE_CURRENT_SOURCE_DIR}/libndcrypto.map"
)

install(TARGETS ndcrypto
  EXPORT netdaemonTargets
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install(FILES ndcrypto.h
  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/netdaemon
)
""")

    # -----------------------------------------------------------------------
    # 6. Fix struct field name in client source
    #    EVALUATION: Migration notes say field is max_conn — WRONG.
    #    ndcore.h defines the field as max_connections.
    # -----------------------------------------------------------------------
    client_src = read("src/client/ndcli.c")
    client_src = re.sub(r'\bcfg\.max_conn\b', 'cfg.max_connections', client_src)
    write("src/client/ndcli.c", client_src)

    # -----------------------------------------------------------------------
    # 7. Fix struct field name in server source (same issue)
    # -----------------------------------------------------------------------
    server_src = read("src/server/ndserver.c")
    server_src = re.sub(r'\bcfg\.max_conn\b', 'cfg.max_connections', server_src)
    write("src/server/ndserver.c", server_src)

    # -----------------------------------------------------------------------
    # 8. Fix pkg-config template
    #    Version must be @PROJECT_VERSION@ (was hardcoded 2.4.1)
    #    Libs must reference -lndcore (was -lnetdaemon)
    # -----------------------------------------------------------------------
    write("pkg/netdaemon.pc.in", """\
prefix=@CMAKE_INSTALL_PREFIX@
libdir=${prefix}/@CMAKE_INSTALL_LIBDIR@
includedir=${prefix}/@CMAKE_INSTALL_INCLUDEDIR@

Name: netdaemon
Description: NetDaemon core library
Version: @PROJECT_VERSION@
Libs: -L${libdir} -lndcore
Cflags: -I${includedir}/netdaemon
""")

    # -----------------------------------------------------------------------
    # 9. Rewrite systemd service unit
    #    EVALUATION: Migration notes say Type=forking with --daemonize — WRONG.
    #    ndserver.c has no fork() call and no --daemonize option handling.
    #    The binary runs in foreground, so Type=simple is correct.
    #    EVALUATION: Migration notes say binary is "netdaemon" — WRONG.
    #    The cmake target and source are ndserver.
    # -----------------------------------------------------------------------
    write("pkg/netdaemon.service", """\
[Unit]
Description=NetDaemon Network Service
After=network.target
Documentation=man:ndserver(8)

[Service]
Type=simple
ExecStart=/usr/local/bin/ndserver --config /etc/netdaemon/netdaemon.conf
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
""")

    # -----------------------------------------------------------------------
    # 10. Fix package manifest conflict
    #     libndcore.so.3 appears in both libnetdaemon.files and
    #     netdaemon-server.files — remove from server manifest
    # -----------------------------------------------------------------------
    server_manifest = read("pkg/manifests/netdaemon-server.files")
    lines = [l for l in server_manifest.splitlines()
             if "libndcore.so" not in l]
    write("pkg/manifests/netdaemon-server.files",
          "\n".join(lines) + "\n")

    # -----------------------------------------------------------------------
    # 11. Remove stale FindLibEvent.cmake
    # -----------------------------------------------------------------------
    find_module = os.path.join(APP, "cmake", "FindLibEvent.cmake")
    if os.path.exists(find_module):
        os.remove(find_module)

    # -----------------------------------------------------------------------
    # Build and verify
    # -----------------------------------------------------------------------
    build_dir = os.path.join(APP, "build")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir)

    subprocess.check_call(["cmake", ".."], cwd=build_dir)
    subprocess.check_call(["cmake", "--build", ".", "--", "-j4"], cwd=build_dir)

    print("Build successful.")


if __name__ == "__main__":
    main()
