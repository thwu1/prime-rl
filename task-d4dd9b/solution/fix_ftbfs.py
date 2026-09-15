#!/usr/bin/env python3
"""
Create CMake package configuration for DataFlow v2 and fix project-side build issues.
Analyzes the installed library structure and project requirements to design proper
CMake config-mode find_package support from scratch.
"""

import os


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def create_dataflow_config():
    """Create DataFlowConfig.cmake with component validation."""
    content = """\
# DataFlow v2 CMake Package Configuration
# Provides imported targets: DataFlow::Core, DataFlow::Pipeline, DataFlow::Codec

include("${CMAKE_CURRENT_LIST_DIR}/DataFlowTargets.cmake")

set(DataFlow_FOUND TRUE)

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
"""
    write_file("/usr/local/lib/cmake/DataFlow/DataFlowConfig.cmake", content)
    print("[CREATE] DataFlowConfig.cmake — component validation and target loading")


def create_dataflow_targets():
    """Create DataFlowTargets.cmake with imported targets and include guard."""
    content = """\
# DataFlow v2 Imported Targets
# Guarded against multiple inclusion from different subdirectories

if(TARGET DataFlow::Core)
  return()
endif()

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
"""
    write_file("/usr/local/lib/cmake/DataFlow/DataFlowTargets.cmake", content)
    print("[CREATE] DataFlowTargets.cmake — Core, Pipeline, Codec targets with include guard")


def create_dataflow_version():
    """Create DataFlowConfigVersion.cmake reporting v2.0.0."""
    content = """\
# DataFlow version compatibility file

set(PACKAGE_VERSION "2.0.0")

if(PACKAGE_FIND_VERSION_RANGE)
    set(PACKAGE_VERSION_COMPATIBLE FALSE)
elseif("${PACKAGE_VERSION}" VERSION_LESS "${PACKAGE_FIND_VERSION}")
    set(PACKAGE_VERSION_COMPATIBLE FALSE)
else()
    set(PACKAGE_VERSION_COMPATIBLE TRUE)
    if("${PACKAGE_VERSION}" VERSION_EQUAL "${PACKAGE_FIND_VERSION}")
        set(PACKAGE_VERSION_EXACT TRUE)
    endif()
endif()
"""
    write_file("/usr/local/lib/cmake/DataFlow/DataFlowConfigVersion.cmake", content)
    print("[CREATE] DataFlowConfigVersion.cmake — reports version 2.0.0")


def fix_component_rename():
    """Replace deprecated Compress component with Codec in executor."""
    path = "/app/src/executor/CMakeLists.txt"
    content = read_file(path)
    content = content.replace("Compress", "Codec")
    write_file(path, content)
    print("[FIX] executor/CMakeLists.txt: Compress -> Codec")


def fix_codegen_path():
    """Fix relative config path in codegen custom command to use absolute path."""
    path = "/app/src/parser/CMakeLists.txt"
    content = read_file(path)
    content = content.replace(
        "--config codegen_config.json",
        "--config ${CMAKE_SOURCE_DIR}/tools/codegen_config.json"
    )
    write_file(path, content)
    print("[FIX] parser/CMakeLists.txt: codegen config uses absolute path")


def fix_header_paths():
    """Migrate v1 include paths to v2 directory layout in all source files."""
    replacements = {
        "#include <dataflow/pipeline.h>": "#include <dataflow/v2/pipeline.h>",
        "#include <dataflow/core.h>": "#include <dataflow/v2/core.h>",
        "#include <dataflow/compress.h>": "#include <dataflow/v2/codec.h>",
    }

    source_files = []
    for root, _dirs, files in os.walk("/app/src"):
        for f in files:
            if f.endswith(('.h', '.cpp', '.hpp', '.cc')):
                source_files.append(os.path.join(root, f))

    fixed = []
    for fpath in source_files:
        content = read_file(fpath)
        changed = False
        for old, new in replacements.items():
            if old in content:
                content = content.replace(old, new)
                changed = True
        if changed:
            write_file(fpath, content)
            fixed.append(os.path.relpath(fpath, "/app/src"))

    print(f"[FIX] Updated v1->v2 header paths in: {fixed}")


if __name__ == '__main__':
    # Phase 1: Create CMake package configuration from scratch
    create_dataflow_config()
    create_dataflow_targets()
    create_dataflow_version()

    # Phase 2: Fix project-side migration issues
    fix_component_rename()
    fix_codegen_path()
    fix_header_paths()

    print("\nAll CMake configuration created and project fixes applied.")
