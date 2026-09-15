# FindNetStream.cmake - Find the NetStream library
#
# NetStream depends on IceCompat for protocol support.

find_package(IceCompat REQUIRED)

find_path(NETSTREAM_INCLUDE_DIR
  NAMES netstream/netstream.h
  PATHS /usr/include /usr/local/include
)

add_library(NetStream::stream INTERFACE IMPORTED)
set_target_properties(NetStream::stream PROPERTIES
  INTERFACE_INCLUDE_DIRECTORIES "${NETSTREAM_INCLUDE_DIR}"
  INTERFACE_LINK_LIBRARIES "IceCompat::core"
)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(NetStream
  DEFAULT_MSG
  NETSTREAM_INCLUDE_DIR
)

set(NETSTREAM_INCLUDE_DIRS ${NETSTREAM_INCLUDE_DIR})
mark_as_advanced(NETSTREAM_INCLUDE_DIR)
