
cmake_minimum_required(VERSION 3.16)
project(inchi_pipeline C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_executable(inchi_pipeline
    src/main.c
    src/inchikey.c
    src/sha256.c
    src/dedup.c
)

target_include_directories(inchi_pipeline PRIVATE src)
