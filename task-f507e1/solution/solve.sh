#!/bin/bash


# Copy modified source files to the compiler directory
cp /solution/Scanner.java /app/Compiler/MJ/Scanner.java
cp /solution/Parser.java /app/Compiler/MJ/Parser.java
cp /solution/Struct.java /app/Compiler/MJ/SymTab/Struct.java
cp /solution/Tab.java /app/Compiler/MJ/SymTab/Tab.java
cp /solution/Operand.java /app/Compiler/MJ/CodeGen/Operand.java
cp /solution/Code.java /app/Compiler/MJ/CodeGen/Code.java
cp /solution/Label.java /app/Compiler/MJ/CodeGen/Label.java

# Compile the modified compiler
cd /app/Compiler
javac MJ/*.java MJ/SymTab/*.java MJ/CodeGen/*.java

# Compile all test programs
for mj_file in /app/test_programs/*.mj; do
    java -cp /app/Compiler MJ.Compiler "$mj_file"
done
