cmake_minimum_required(VERSION 3.16)
project(ManipulatorIK LANGUAGES CXX)


set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# --- Shared library for FK/IK computations ---
add_library(manipulator_core SHARED
    src/fk.cpp
    src/ik.cpp
)
target_include_directories(manipulator_core PRIVATE
    ${PROJECT_SOURCE_DIR}/include
)
target_link_libraries(manipulator_core PRIVATE m)
set_target_properties(manipulator_core PROPERTIES POSITION_INDEPENDENT_CODE OFF)

# --- Main CLI executable ---
add_executable(manipulator_cli src/main.cpp)
target_link_libraries(manipulator_cli PRIVATE manipulator_core)
set_target_properties(manipulator_cli PROPERTIES OUTPUT_NAME manipulator)

# --- CTest integration ---
enable_testing()
add_test(NAME verify_roundtrip
    COMMAND $<TARGET_FILE:manipulator_cli> --verify 500
)
