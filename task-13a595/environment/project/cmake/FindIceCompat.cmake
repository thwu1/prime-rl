# FindIceCompat.cmake - Find the IceCompat compatibility library
#
# This module defines:
#   ICECOMPAT_FOUND        - True if IceCompat was found
#   ICECOMPAT_INCLUDE_DIRS - IceCompat include directories
#   ICECOMPAT_LIBRARIES    - IceCompat libraries
#
# Imported targets:
#   IceCompat::core - The IceCompat interface library

find_path(ICECOMPAT_INCLUDE_DIR
  NAMES icecompat/icecompat.h
  PATHS /usr/include /usr/local/include
)

add_library(IceCompat::core INTERFACE IMPORTED)
set_target_properties(IceCompat::core PROPERTIES
  INTERFACE_INCLUDE_DIRECTORIES "${ICECOMPAT_INCLUDE_DIR}"
)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(IceCompat
  DEFAULT_MSG
  ICECOMPAT_INCLUDE_DIR
)

set(ICECOMPAT_INCLUDE_DIRS ${ICECOMPAT_INCLUDE_DIR})
mark_as_advanced(ICECOMPAT_INCLUDE_DIR)
