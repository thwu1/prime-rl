cmake_minimum_required(VERSION 3.16)
project(netmon VERSION 2.0.0 LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# ABI policy: hide internal symbols, export only the public API
set(CMAKE_C_VISIBILITY_PRESET hidden)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)

# Add project cmake modules
list(APPEND CMAKE_MODULE_PATH "${CMAKE_SOURCE_DIR}/cmake")

# Find dependencies
find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_package(OpenSSL REQUIRED)
find_package(IceCompat REQUIRED)
find_package(NetStream REQUIRED)

# Debian hardening flags
add_compile_options(
  $<$<COMPILE_LANGUAGE:C>:-Werror=implicit-function-declaration>
)

# Generate config header via codegen
add_custom_command(
  OUTPUT ${CMAKE_BINARY_DIR}/generated_config.h
  COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tools/codegen.py
    --output ${CMAKE_BINARY_DIR}/generated_config.h
    --version ${PROJECT_VERSION}
  DEPENDS ${CMAKE_SOURCE_DIR}/tools/codegen.py
  COMMENT "Generating config header"
)
add_custom_target(generate_config DEPENDS ${CMAKE_BINARY_DIR}/generated_config.h)

# Library target
add_library(netmon SHARED
  src/netmon.c
  src/resolver.c
  src/monitor.cpp
)
target_include_directories(netmon
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_SOURCE_DIR}/include>
    $<BUILD_INTERFACE:${CMAKE_BINARY_DIR}>
    $<INSTALL_INTERFACE:include/netmon-v2>
  PRIVATE
    ${CMAKE_SOURCE_DIR}/src
)
target_link_libraries(netmon
  PUBLIC OpenSSL::SSL OpenSSL::Crypto
  PRIVATE IceCompat::core NetStream::stream
)
add_dependencies(netmon generate_config)

# Shared library versioning
set_target_properties(netmon PROPERTIES
  VERSION 2
  SOVERSION 2.0.0
)

# Install rules
include(GNUInstallDirs)
install(TARGETS netmon
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
)
install(DIRECTORY include/netmon-v2/
  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/netmon-v2
)
install(FILES ${CMAKE_BINARY_DIR}/generated_config.h
  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/netmon-v2
)

# pkg-config
configure_file(netmon.pc.in ${CMAKE_BINARY_DIR}/netmon.pc @ONLY)
install(FILES ${CMAKE_BINARY_DIR}/netmon.pc
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/pkgconfig
)
