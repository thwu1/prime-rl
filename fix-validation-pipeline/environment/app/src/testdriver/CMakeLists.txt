cmake_minimum_required(VERSION 3.5)
project(validate_driver)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++17 -Wall -DNIST_EXTERN_API_VERSION -DNIST_EXTERN_STRUCTS_VERSION")
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../include)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../../bin)

add_executable(validate validate.cpp util.cpp)
target_link_libraries(validate $ENV{EVAL_IMPL_LIB})
