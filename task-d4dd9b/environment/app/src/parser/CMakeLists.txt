find_package(DataFlow REQUIRED COMPONENTS Core Pipeline)

add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/generated_rules.h
    COMMAND python3 ${CMAKE_SOURCE_DIR}/tools/codegen.py
        --config codegen_config.json
        --output ${CMAKE_CURRENT_BINARY_DIR}/generated_rules.h
    DEPENDS ${CMAKE_SOURCE_DIR}/tools/codegen.py
    COMMENT "Generating parser rules..."
)

add_library(parser
    parser.cpp
    ${CMAKE_CURRENT_BINARY_DIR}/generated_rules.h
)
target_include_directories(parser PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_BINARY_DIR}
)
target_link_libraries(parser PUBLIC DataFlow::Pipeline)
