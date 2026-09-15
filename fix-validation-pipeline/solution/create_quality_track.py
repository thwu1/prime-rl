#!/usr/bin/env python3
"""Create all files needed for the quality assessment track."""

import os


def write_file(path, content, executable=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    if executable:
        os.chmod(path, 0o755)
    print(f"Created {path}")


# --- Quality implementation header ---
write_file("/app/src/impl_quality/evalqualityimpl.h", """\
#ifndef EVALQUALITYIMPL_H_
#define EVALQUALITYIMPL_H_

#include "eval_quality.h"

namespace EVAL_QUALITY {

class EvalQualityImpl : public Interface {
public:
    EvalQualityImpl();
    ~EvalQualityImpl() override;

    EVAL::ReturnStatus initialize(const std::string &configDir) override;

    EVAL::ReturnStatus scalarQuality(
        const EVAL::Image &image,
        double &quality) override;

    EVAL::ReturnStatus vectorQuality(
        const EVAL::Image &image,
        std::vector<QualityAttribute> &qualities) override;

    static std::shared_ptr<Interface> getImplementation();

private:
    std::string configDir;
};

}

#endif
""")

# --- Quality implementation source ---
write_file("/app/src/impl_quality/evalqualityimpl.cpp", """\
#include <cstring>
#include "evalqualityimpl.h"

using namespace std;
using namespace EVAL;
using namespace EVAL_QUALITY;

EvalQualityImpl::EvalQualityImpl() {}
EvalQualityImpl::~EvalQualityImpl() {}

ReturnStatus
EvalQualityImpl::initialize(const string &configDir)
{
    this->configDir = configDir;
    return ReturnStatus(ReturnCode::Success);
}

ReturnStatus
EvalQualityImpl::scalarQuality(
    const Image &image,
    double &quality)
{
    quality = static_cast<double>((image.width * image.height) % 101);
    return ReturnStatus(ReturnCode::Success);
}

ReturnStatus
EvalQualityImpl::vectorQuality(
    const Image &image,
    vector<QualityAttribute> &qualities)
{
    qualities.clear();
    uint32_t seed = image.width + image.height;
    qualities.push_back({QualityAttribute::Measure::Sharpness,
        static_cast<double>((seed * 7) % 101)});
    qualities.push_back({QualityAttribute::Measure::Exposure,
        static_cast<double>((seed * 13) % 101)});
    qualities.push_back({QualityAttribute::Measure::UniformBackground,
        static_cast<double>((seed * 19) % 101)});
    qualities.push_back({QualityAttribute::Measure::GrayscaleDensity,
        static_cast<double>((seed * 23) % 101)});
    return ReturnStatus(ReturnCode::Success);
}

shared_ptr<Interface>
Interface::getImplementation()
{
    return make_shared<EvalQualityImpl>();
}
""")

# --- Quality CMakeLists.txt ---
write_file("/app/src/impl_quality/CMakeLists.txt", """\
cmake_minimum_required(VERSION 3.5)
project(evalQualityImpl)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++17")
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../include)

set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../../lib)

add_library(eval_quality_null_001 SHARED evalqualityimpl.cpp)
""")

# --- Build quality impl script ---
write_file("/app/scripts/build_quality_impl.sh", """\
#!/bin/bash
echo "Building quality implementation library..."
root=$(pwd)
cd src/impl_quality
rm -rf build
mkdir -p build
cd build
cmake ../ 2>&1
retcode=$?
if [[ $retcode != 0 ]]; then
    cd "$root"
    echo "[ERROR] Quality cmake configuration failed."
    exit 1
fi
make 2>&1
retcode=$?
cd "$root"
if [ $retcode != 0 ]; then
    echo "[ERROR] Quality implementation library compilation failed."
    exit 1
fi
numLibs=$(ls lib/libeval_quality_*.so 2>/dev/null | wc -l)
if [ $numLibs -eq 0 ]; then
    echo "[ERROR] No quality implementation library found in lib/."
    exit 1
fi
echo "[SUCCESS] Quality implementation library built."
exit 0
""", executable=True)

# --- Compile and link quality test driver ---
write_file("/app/scripts/compile_and_link_quality.sh", r"""#!/bin/bash
root=$(pwd)
libroot=$root/lib

numLibs=$(ls $libroot/libeval_quality_*_???.so 2>/dev/null | wc -l)
if [ $numLibs -ne 1 ]; then
    echo "[ERROR] Expected exactly 1 libeval_quality_*.so, found $numLibs"
    exit 1
fi

libpath=$(ls $libroot/libeval_quality_*_???.so)
libname=$(basename $libpath .so | sed 's/^lib//')

echo "Compiling quality test driver..."
g++ -std=c++17 -Wall -DNIST_EXTERN_STRUCTS_VERSION -DNIST_EXTERN_QUALITY_API_VERSION \
    -I src/include \
    -o bin/validate_quality \
    src/testdriver/validate_quality.cpp src/testdriver/util.cpp \
    -L lib -l${libname} -Wl,-rpath,${root}/lib

if [ ! -f "bin/validate_quality" ]; then
    echo "[ERROR] bin/validate_quality not found after build."
    exit 1
fi
echo "[SUCCESS] Built bin/validate_quality."
exit 0
""", executable=True)

# --- Run quality test driver ---
write_file("/app/scripts/run_quality_testdriver.sh", """\
#!/bin/bash
root=$(pwd)
bin=$root/bin
configDir=$root/config
outputDir=$root/validation

echo "Running quality assessment..."
$bin/validate_quality -c "$configDir" -o "$outputDir" -i input/quality.txt
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[ERROR] Quality assessment failed."
    exit 1
fi
echo "[SUCCESS] Quality assessment completed."
exit 0
""", executable=True)

# --- Extended run_validate.sh with both tracks ---
# Use raw string to avoid Python escape issues with awk $ and \n
write_file("/app/run_validate.sh", r"""#!/bin/bash

success=0
failure=1

# =============================================
# 1:1 VERIFICATION TRACK
# =============================================

echo "============================================"
echo "Step 1: Building 1:1 implementation library"
echo "============================================"
scripts/build_impl.sh
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[FAILED] Implementation library build failed."
    exit $failure
fi

echo ""
echo "============================================"
echo "Step 2: Compiling and linking 1:1 test driver"
echo "============================================"
scripts/compile_and_link.sh
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[FAILED] Test driver compilation failed."
    exit $failure
fi

echo ""
echo "============================================"
echo "Step 3: Running 1:1 test driver"
echo "============================================"
export LD_LIBRARY_PATH=$(pwd)/lib
rm -rf validation templates
mkdir -p validation templates
scripts/run_testdriver.sh
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[FAILED] Test driver execution failed."
    exit $failure
fi

echo ""
echo "============================================"
echo "Step 4: Validating 1:1 output logs"
echo "============================================"
outputDir="validation"

for input in enroll verif match
do
    if [ ! -f "$outputDir/$input.log" ]; then
        echo "[ERROR] Missing output log: $outputDir/$input.log"
        exit $failure
    fi

    numInputLines=$(wc -l < input/$input.txt)
    numLogLines=$(sed '1d' $outputDir/$input.log | wc -l)
    if [ "$numInputLines" != "$numLogLines" ]; then
        echo "[ERROR] $outputDir/$input.log has wrong number of lines."
        exit $failure
    fi

    numFail=$(sed '1d' $outputDir/$input.log | awk '{ if($4!=0) print }' | wc -l)
    if [ "$numFail" != "0" ]; then
        echo "[ERROR] $input.log contains $numFail entries with non-successful return codes."
        exit $failure
    fi

    if [ "$input" == "match" ]; then
        numNeg=$(sed '1d' $outputDir/$input.log | awk '{ if($4==0 && ($3+0)<0) print }' | wc -l)
        if [ "$numNeg" -gt "0" ]; then
            echo "[ERROR] $numNeg negative match scores detected."
            exit $failure
        fi

        minUniq=$(echo "$numInputLines * 0.5" | bc | awk '{printf("%d\n",$1 + 0.5)}')
        numUniq=$(sed '1d' $outputDir/$input.log | awk '{ print $3 }' | sort -u | wc -l)
        if [ "$numUniq" -lt "$minUniq" ]; then
            echo "[WARNING] Only $numUniq unique match scores."
        fi
    fi
done

echo "[SUCCESS] 1:1 validation checks passed."

# =============================================
# QUALITY ASSESSMENT TRACK
# =============================================

echo ""
echo "============================================"
echo "Step 5: Building quality implementation library"
echo "============================================"
scripts/build_quality_impl.sh
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[FAILED] Quality implementation library build failed."
    exit $failure
fi

echo ""
echo "============================================"
echo "Step 6: Compiling and linking quality test driver"
echo "============================================"
scripts/compile_and_link_quality.sh
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[FAILED] Quality test driver compilation failed."
    exit $failure
fi

echo ""
echo "============================================"
echo "Step 7: Running quality test driver"
echo "============================================"
scripts/run_quality_testdriver.sh
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[FAILED] Quality test driver execution failed."
    exit $failure
fi

echo ""
echo "============================================"
echo "Step 8: Validating quality output logs"
echo "============================================"

if [ ! -f "$outputDir/quality.log" ]; then
    echo "[ERROR] Missing output log: $outputDir/quality.log"
    exit $failure
fi

numInputLines=$(wc -l < input/quality.txt)
numLogLines=$(sed '1d' $outputDir/quality.log | wc -l)
if [ "$numInputLines" != "$numLogLines" ]; then
    echo "[ERROR] quality.log has wrong number of lines."
    exit $failure
fi

numFail=$(sed '1d' $outputDir/quality.log | awk '{ if($3!=0) print }' | wc -l)
if [ "$numFail" != "0" ]; then
    echo "[ERROR] quality.log contains $numFail entries with non-successful return codes."
    exit $failure
fi

numBad=$(sed '1d' $outputDir/quality.log | awk '{ if(($2+0)<0 || ($2+0)>100) print }' | wc -l)
if [ "$numBad" != "0" ]; then
    echo "[ERROR] $numBad quality scores out of [0, 100] range."
    exit $failure
fi

for col in 4 5 6 7; do
    numBad=$(sed '1d' $outputDir/quality.log | awk -v c=$col '{ if(($c+0)<0 || ($c+0)>100) print }' | wc -l)
    if [ "$numBad" != "0" ]; then
        echo "[ERROR] $numBad quality attribute values out of [0, 100] in column $col."
        exit $failure
    fi
done

echo "[SUCCESS] Quality validation checks passed."

# Create submission archive
echo ""
echo -n "Creating submission package... "
libstring=$(basename $(ls ./lib/libeval_11_*_???.so))
libstring=${libstring%.so}
tar -zcf ${libstring}.tar.gz ./config ./lib ./validation ./doc 2>/dev/null
echo "[SUCCESS]"

echo ""
echo "============================================"
echo "ALL TRACKS VALIDATED SUCCESSFULLY"
echo "============================================"

exit $success
""", executable=True)

print("Quality track files created successfully.")
