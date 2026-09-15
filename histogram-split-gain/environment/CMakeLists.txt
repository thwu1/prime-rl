cmake_minimum_required(VERSION 3.16)
project(HistogramSplitFinder LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nlohmann_json 3.2.0 REQUIRED)

# Numeric stability parameter for floating-point gain computation
set(NUMERIC_EPSILON "1e-3" CACHE STRING "Epsilon for split gain numerical stability")

add_executable(histogram_split_finder main.cpp)

target_link_libraries(histogram_split_finder PRIVATE nlohmann_json::nlohmann_json)

target_compile_definitions(histogram_split_finder PRIVATE
    SPLIT_EPSILON=${NUMERIC_EPSILON}
)

target_compile_options(histogram_split_finder PRIVATE -O2 -Wall)

# Place binary in project root directory
set_target_properties(histogram_split_finder PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}
)
