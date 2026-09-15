# FindLibEvent.cmake - Locate the libevent library
#
# Defines:
#   LIBEVENT_FOUND        - system has libevent
#   LIBEVENT_INCLUDE_DIR  - libevent include directory
#   LIBEVENT_LIBRARY      - libevent library path
#   LibEvent::LibEvent    - imported target

include(FindPackageHandleStandardArgs)

find_path(LIBEVENT_INCLUDE_DIR
  NAMES event2/event.h event.h
  PATHS /usr/include /usr/local/include
  DOC "libevent include directory"
)

find_library(LIBEVENT_LIBRARY
  NAMES event event_core event_extra
  PATHS /usr/lib /usr/local/lib /usr/lib/x86_64-linux-gnu
  DOC "libevent library path"
)

find_package_handle_standard_args(LibEvent
  REQUIRED_VARS LIBEVENT_LIBRARY LIBEVENT_INCLUDE_DIR
  FAIL_MESSAGE "LibEvent: install libevent-dev to satisfy this dependency"
)

if(LIBEVENT_FOUND)
  if(NOT TARGET LibEvent::LibEvent)
    add_library(LibEvent::LibEvent UNKNOWN IMPORTED)
    set_target_properties(LibEvent::LibEvent PROPERTIES
      IMPORTED_LOCATION "${LIBEVENT_LIBRARY}"
      INTERFACE_INCLUDE_DIRECTORIES "${LIBEVENT_INCLUDE_DIR}"
    )
  endif()
endif()

mark_as_advanced(LIBEVENT_INCLUDE_DIR LIBEVENT_LIBRARY)
