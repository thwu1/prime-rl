add_executable(ndserver ndserver.c)

target_link_libraries(ndserver PRIVATE ndcore ndcrypto)

install(TARGETS ndserver RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
