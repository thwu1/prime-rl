find_package(DataFlow 2.0 REQUIRED COMPONENTS Core Compress)

add_library(executor
    executor.cpp
)
target_include_directories(executor PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(executor PUBLIC DataFlow::Core DataFlow::Compress)
