# DataFlow v2 CMake Configuration File
# Provides imported targets: DataFlow::Core, DataFlow::Pipeline, DataFlow::Codec

include("${CMAKE_CURRENT_LIST_DIR}/DataFlowTargets.cmake")

set(DataFlow_FOUND TRUE)

# Available components in DataFlow v2
set(_DATAFLOW_AVAILABLE_COMPONENTS Core Pipeline Codec)

if(DataFlow_FIND_COMPONENTS)
    foreach(_comp ${DataFlow_FIND_COMPONENTS})
        if(NOT _comp IN_LIST _DATAFLOW_AVAILABLE_COMPONENTS)
            set(DataFlow_${_comp}_FOUND FALSE)
            if(DataFlow_FIND_REQUIRED_${_comp})
                set(DataFlow_FOUND FALSE)
                message(FATAL_ERROR
                    "DataFlow: Required component '${_comp}' not found. "
                    "Available components: ${_DATAFLOW_AVAILABLE_COMPONENTS}")
            endif()
        else()
            set(DataFlow_${_comp}_FOUND TRUE)
        endif()
    endforeach()
endif()
