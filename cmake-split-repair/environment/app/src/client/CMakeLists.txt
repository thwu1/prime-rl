add_executable(ndcli ndcli.c)

target_link_libraries(ndcli PRIVATE ndcore ndcrypto)

install(TARGETS ndcli RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
