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
)

install(TARGETS ndcrypto
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install(FILES ndcrypto.h
  DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/netdaemon
)
