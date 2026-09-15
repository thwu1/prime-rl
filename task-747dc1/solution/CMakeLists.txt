cmake_minimum_required(VERSION 3.20)
project(fredbuf LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(fredbuf STATIC
    src/piece_table.cpp
    src/undo_tree.cpp
    src/myers_diff.cpp
)
target_include_directories(fredbuf PUBLIC include)

add_executable(fredbuf_test test/test_main.cpp)
target_link_libraries(fredbuf_test PRIVATE fredbuf)
