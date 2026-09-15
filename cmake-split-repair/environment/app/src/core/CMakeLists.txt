add_library(ndcore
  ndcore.c
  ndcore.h
)

target_include_directories(ndcore PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/netdaemon>
)

# libevent for async event handling
target_link_libraries(ndcore PRIVATE event)

set_target_properties(ndcore PROPERTIES
  VERSION ${ND_VERSION}
  SOVERSION ${ND_SOVERSION}
  OUTPUT_NAME ndcore
)

install(TARGETS ndcore
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install(FILES ndcore.h
  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/netdaemon
)
