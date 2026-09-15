cmake_minimum_required(VERSION 3.16)
project(ExprParser LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(parser
    src/main.cpp
    src/parser.cpp
)

target_include_directories(parser PRIVATE ${PROJECT_BINARY_DIR}/include)
