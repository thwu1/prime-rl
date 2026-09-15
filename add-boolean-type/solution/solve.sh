#!/bin/bash

# Apply all compiler modifications to add boolean data type
python3 /solution/patch_compiler.py

# Recompile the modified compiler
cd /app/Compiler && javac MJ/Compiler.java MJ/Run.java MJ/Decode.java

echo "Compiler modified and recompiled. Testing with Eratos..."
echo "10" | java -cp /app/Compiler MJ.Compiler /app/Compiler/Eratos.mj
echo "10" | java -cp /app/Compiler MJ.Run /app/Compiler/Eratos.obj
echo ""
echo "Regression test passed."
