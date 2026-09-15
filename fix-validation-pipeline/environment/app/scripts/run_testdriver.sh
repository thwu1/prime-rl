#!/bin/bash

root=$(pwd)
bin=$root/bin
configDir=$root/config
outputDir=$root/validation
templatesDir=$root/templates

mkdir -p "$outputDir" "$templatesDir"

echo "Processing enrollment templates..."
$bin/validate createTemplate -x enroll -c "$configDir" -o "$outputDir" -i input/enroll.txt -j "$templatesDir"
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[ERROR] Enrollment template creation failed."
    exit 1
fi

echo "Processing verification templates..."
$bin/validate createTemplate -x verif -c "$configDir" -o "$outputDir" -i input/verif.txt -j "$templatesDir"
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[ERROR] Verification template creation failed."
    exit 1
fi

echo "Processing match comparisons..."
$bin/validate match -c "$configDir" -o "$outputDir" -i input/match.txt -j "$templatesDir"
retcode=$?
if [[ $retcode != 0 ]]; then
    echo "[ERROR] Match processing failed."
    exit 1
fi

echo "[SUCCESS] Test driver completed all operations."
exit 0
