cmake_minimum_required(VERSION 3.14)
project(netdaemon VERSION 3.0.0 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# Dependencies
find_package(OpenSSL REQUIRED)
find_package(LibEvent REQUIRED)

# Build options
option(BUILD_SHARED_LIBS "Build shared libraries" ON)
option(ENABLE_SERVER "Build server daemon" ON)
option(ENABLE_CLIENT "Build client tools" ON)

# Library versioning
set(ND_SOVERSION 2)
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

include(GNUInstallDirs)
