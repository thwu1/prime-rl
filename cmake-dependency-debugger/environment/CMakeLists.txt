# Production Renderer Dependency Build System
# Builds all third-party dependencies from source using ExternalProject_Add
#
cmake_minimum_required(VERSION 3.23.1)
project(RendererDependencies)

set(INSTALL_DIR "/opt/renderer/installs" CACHE PATH "Install prefix for all dependencies")
set(JOBS_ARG "-j8" CACHE STRING "Parallel build jobs argument")

include(ExternalProject)

# ===========================================================================
# zlib - compression library (required by OpenEXR, libtiff)
# ===========================================================================
ExternalProject_Add(zlib
    GIT_REPOSITORY https://github.com/madler/zlib.git
    GIT_TAG v1.3.1
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
    BUILD_COMMAND cmake --build . -- ${JOBS_ARG}
)

# ===========================================================================
# OpenEXR - HDR image format (Academy Software Foundation)
# ===========================================================================
ExternalProject_Add(OpenEXR
    GIT_REPOSITORY https://github.com/AcademySoftwareFoundation/openexr.git
    GIT_TAG v3.1.8
    DEPENDS zlib OpenColorIO
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_PREFIX_PATH=${INSTALL_DIR}
        -DBUILD_SHARED_LIBS=OFF
        -DBUILD_TESTING=OFF
        -DOPENEXR_INSTALL_EXAMPLES=OFF
    BUILD_COMMAND cmake --build . -- ${JOBS_ARG}
)

# ===========================================================================
# libjpeg-turbo - JPEG codec with SIMD acceleration
# ===========================================================================
ExternalProject_Add(libjpeg-turbo
    GIT_REPOSITORY https://github.com/libjpeg-turbo/libjpeg-turbo.git
    GIT_TAG 3.0.1
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
    BUILD_COMMAND cmake --build . -- ${JOBS_ARG}
)

# ===========================================================================
# libtiff - TIFF image format support
# ===========================================================================
ExternalProject_Add(libtiff
    GIT_REPOSITORY https://gitlab.com/libtiff/libtiff.git
    GIT_TAG v4.6.0
    DEPENDS zlib
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_PREFIX_PATH=${INSTALL_DIR}
        -Djpeg=ON
    BUILD_COMMAND cmake --build . -- ${JOBS_ARG}
)

# ===========================================================================
# Boost - C++ utility libraries
# ===========================================================================
ExternalProject_Add(Boost
    URL https://boostorg.jfrog.io/artifactory/main/release/1.82.0/source/boost_1_82_0.tar.gz
    BUILD_IN_SOURCE 1
    CONFIGURE_COMMAND ./bootstrap.sh --prefix=${INSTALL_DIR}
    BUILD_COMMAND ./b2 ${JOBS_ARG} install
    INSTALL_COMMAND ""
)

# ===========================================================================
# Random123 - counter-based random number generators (header-only)
# ===========================================================================
ExternalProject_Add(Random123
    GIT_REPOSITORY https://github.com/DEShawResearch/random123.git
    GIT_TAG v1.14.0
    BUILD_IN_SOURCE 1
    CONFIGURE_COMMAND ""
    BUILD_COMMAND ""
    INSTALL_COMMAND ${CMAKE_COMMAND} -E copy_directory
        <SOURCE_DIR>/include ${INSTALL_DIR}/include
)

# ===========================================================================
# ISPC - Intel SPMD Program Compiler (pre-built binary)
# ===========================================================================
ExternalProject_Add(ISPC
    URL https://github.com/ispc/ispc/releases/download/v1.21.0/ispc-v1.21.0-linux.tar.gz
    BUILD_IN_SOURCE 1
    CONFIGURE_COMMAND ""
    BUILD_COMMAND ""
    INSTALL_COMMAND ${CMAKE_COMMAND} -E copy
        <SOURCE_DIR>/bin/ispc ${INSTALL_DIR}/bin/ispc
)

# ===========================================================================
# TBB - Threading Building Blocks
# ===========================================================================
ExternalProject_Add(TBB
    GIT_REPOSITORY https://github.com/oneapi-src/oneTBB.git
    GIT_TAG v2020.3.3
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
        -DTBB_TEST=OFF
    BUILD_COMMAND cmake --build . -- ${JOBS_ARG}
)

# ===========================================================================
# OpenColorIO - color management framework (Academy Software Foundation)
# ===========================================================================
ExternalProject_Add(OpenColorIO
    GIT_REPOSITORY https://github.com/AcademySoftwareFoundation/OpenColorIO.git
    GIT_TAG v2.2.1
    DEPENDS OpenEXR
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_PREFIX_PATH=${INSTALL_DIR}
        -DBUILD_SHARED_LIBS=ON
        -DOCIO_BUILD_APPS=OFF
        -DOCIO_BUILD_GPU_TESTS=OFF
        -DCMAKE_CXX_STANDARD=17
    BUILD_COMMAND cmake --build . -- ${JOBS_ARG}
)

# ===========================================================================
# Embree - high-performance ray tracing kernels (Intel)
# ===========================================================================
ExternalProject_Add(Embree
    GIT_REPOSITORY https://github.com/embree/embree.git
    GIT_TAG v4.2.0
    DEPENDS ISPC TBB
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_PREFIX_PATH=${INSTALL_DIR}
        -DBUILD_SHARED_LIBS=ON
        -DEMBREE_ISPC_SUPPORT=ON
        -DISPC_EXECUTABLE=${INSTALL_DIR}/ispc/bin/ispc
        -DEMBREE_RAY_MASK=ON
        -DEMBREE_MAX_ISA=AVX512SKX
        -DEMBREE_TUTORIALS=OFF
    BUILD_COMMAND cmake --build . -- ${JOBS_ARG}
)

# ===========================================================================
# OpenImageIO - image I/O library (Academy Software Foundation)
# ===========================================================================
ExternalProject_Add(OpenImageIO
    GIT_REPOSITORY https://github.com/AcademySoftwareFoundation/OpenImageIO.git
    GIT_TAG v2.4.8.0
    DEPENDS OpenEXR libtiff Boost
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_PREFIX_PATH=${INSTALL_DIR}
        -DBUILD_SHARED_LIBS=ON
        -DUSE_PYTHON=ON
        -DUSE_QT=OFF
        -DBUILD_TESTING=OFF
    BUILD_COMMAND cmake --build . -- ${JOBS_ARG}
)

# ===========================================================================
# OpenSubdiv - subdivision surface evaluation library (Pixar)
# ===========================================================================
ExternalProject_Add(OpenSubdiv
    GIT_REPOSITORY https://github.com/PixarAnimationStudios/OpenSubdiv.git
    GIT_TAG v3.5.0
    DEPENDS TBB
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_PREFIX_PATH=${INSTALL_DIR}
        -DNO_PTEX=ON
        -DNO_OMP=ON
        -DNO_CUDA=ON
        -DNO_REGRESSION=ON
    BUILD_COMMAND cmake --build . -- ${JOBS_ARG}
)

# ===========================================================================
# USD - Universal Scene Description (Pixar)
# ===========================================================================
ExternalProject_Add(USD
    GIT_REPOSITORY https://github.com/PixarAnimationStudios/OpenUSD.git
    GIT_TAG v23.02
    DEPENDS Boost TBB OpenEXR OpenSubdiv OpenImageIO
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_PREFIX_PATH=${INSTALL_DIR}
        -DPXR_BUILD_TESTS=OFF
        -DPXR_BUILD_EXAMPLES=OFF
        -DPXR_BUILD_TUTORIALS=OFF
        -DPXR_BUILD_USD_TOOLS=OFF
        -DPXR_ENABLE_PYTHON_SUPPORT=ON
    BUILD_COMMAND cmake --build . -- ${JOBS_ARG}
)
