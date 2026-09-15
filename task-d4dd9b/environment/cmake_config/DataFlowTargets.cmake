# DataFlow imported targets
# Auto-generated — do not edit manually

set(_DATAFLOW_IMPORT_PREFIX "${CMAKE_CURRENT_LIST_DIR}/../../..")

add_library(DataFlow::Core STATIC IMPORTED)
set_target_properties(DataFlow::Core PROPERTIES
    IMPORTED_LOCATION "${_DATAFLOW_IMPORT_PREFIX}/lib/libdataflow.a"
    INTERFACE_INCLUDE_DIRECTORIES "${_DATAFLOW_IMPORT_PREFIX}/include"
)

add_library(DataFlow::Pipeline STATIC IMPORTED)
set_target_properties(DataFlow::Pipeline PROPERTIES
    IMPORTED_LOCATION "${_DATAFLOW_IMPORT_PREFIX}/lib/libdataflow.a"
    INTERFACE_INCLUDE_DIRECTORIES "${_DATAFLOW_IMPORT_PREFIX}/include"
    INTERFACE_LINK_LIBRARIES "DataFlow::Core"
)

add_library(DataFlow::Codec STATIC IMPORTED)
set_target_properties(DataFlow::Codec PROPERTIES
    IMPORTED_LOCATION "${_DATAFLOW_IMPORT_PREFIX}/lib/libdataflow.a"
    INTERFACE_INCLUDE_DIRECTORIES "${_DATAFLOW_IMPORT_PREFIX}/include"
    INTERFACE_LINK_LIBRARIES "DataFlow::Core"
)
