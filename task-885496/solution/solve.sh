#!/bin/bash

# Copy assembler and simulator to the working directory
cp /solution/assembler.py /app/assembler.py
cp /solution/simulator.py /app/simulator.py

# Verify the solution works by running a quick self-test
cd /app
python3 -c "
from assembler import assemble
from simulator import simulate

# Test matrix addition
matadd_src = '''
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #0
CONST R2, #8
CONST R3, #16
ADD R4, R1, R0
LDR R4, R4
ADD R5, R2, R0
LDR R5, R5
ADD R6, R4, R5
ADD R7, R3, R0
STR R7, R6
RET
'''
asm = assemble(matadd_src)
data = [0,1,2,3,4,5,6,7, 0,1,2,3,4,5,6,7]
result = simulate(asm['program'], data, thread_count=8)
expected = [0,2,4,6,8,10,12,14]
for i, exp in enumerate(expected):
    actual = result['data_memory'][16+i]
    assert actual == exp, f'matadd[{i}] expected {exp}, got {actual}'

# Test matrix multiplication
matmul_src = '''
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #1
CONST R2, #2
CONST R3, #0
CONST R4, #4
CONST R5, #8
DIV R6, R0, R2
MUL R7, R6, R2
SUB R7, R0, R7
CONST R8, #0
CONST R9, #0
LOOP:
  MUL R10, R6, R2
  ADD R10, R10, R9
  ADD R10, R10, R3
  LDR R10, R10
  MUL R11, R9, R2
  ADD R11, R11, R7
  ADD R11, R11, R4
  LDR R11, R11
  MUL R12, R10, R11
  ADD R8, R8, R12
  ADD R9, R9, R1
  CMP R9, R2
  BRn LOOP
ADD R9, R5, R0
STR R9, R8
RET
'''
asm = assemble(matmul_src)
data = [1,2,3,4, 1,2,3,4]
result = simulate(asm['program'], data, thread_count=4)
expected_mm = [7, 10, 15, 22]
for i, exp in enumerate(expected_mm):
    actual = result['data_memory'][8+i]
    assert actual == exp, f'matmul[{i}] expected {exp}, got {actual}'

print('All self-tests passed.')
"
