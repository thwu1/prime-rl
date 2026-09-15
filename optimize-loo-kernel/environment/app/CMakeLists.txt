cmake_minimum_required(VERSION 3.16)
project(AnalyticsTool LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Source files for the analytics tool
add_executable(analytics_tool main.cpp)

target_compile_options(analytics_tool PRIVATE -g -O0 -Wall)

set_target_properties(analytics_tool PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)
