#!/bin/bash

success=0
failure=1

# Step 1: Build implementation library
echo "============================================"
echo "Step 1: Building 1:1 implementation library"
echo "============================================"
scripts/build_impl.sh
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[FAILED] Implementation library build failed."
    exit $failure
fi

# Step 2: Compile and link test driver
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

# Step 3: Run test driver
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

# Step 4: Sanity check validation output
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
        echo "        Expected $numInputLines data lines, got $numLogLines."
        exit $failure
    fi

    # Check return codes (column 4 in all log formats)
    numFail=$(sed '1d' $outputDir/$input.log | awk '{ if($4!=0) print }' | wc -l)
    if [ "$numFail" != "0" ]; then
        echo "[ERROR] $input.log contains $numFail entries with non-successful return codes:"
        sed '1d' $outputDir/$input.log | awk '{ if($4!=0) print }'
        exit $failure
    fi

    if [ "$input" == "match" ]; then
        # Check for negative match scores (score is column 3, return code is column 4)
        numNeg=$(sed '1d' $outputDir/$input.log | awk '{ if($4==0 && ($3+0)<0) print }' | wc -l)
        if [ "$numNeg" -gt "0" ]; then
            echo "[ERROR] $numNeg negative match scores detected. Scores must be non-negative per API spec."
            exit $failure
        fi

        # Check match score uniqueness (>50%)
        minUniq=$(echo "$numInputLines * 0.5" | bc | awk '{printf("%d\n",$1 + 0.5)}')
        numUniq=$(sed '1d' $outputDir/$input.log | awk '{ print $3 }' | sort -u | wc -l)
        if [ "$numUniq" -lt "$minUniq" ]; then
            echo "[WARNING] Only $numUniq unique match scores out of $numInputLines (need $minUniq for 50%)."
        fi
    fi
done

echo ""
echo "[SUCCESS] 1:1 validation checks passed."

# Create submission archive
echo -n "Creating submission package... "
libstring=$(basename $(ls ./lib/libeval_11_*_???.so))
libstring=${libstring%.so}
tar -zcf ${libstring}.tar.gz ./config ./lib ./validation ./doc 2>/dev/null
echo "[SUCCESS]"
echo "Submission package: ${libstring}.tar.gz"

exit $success
