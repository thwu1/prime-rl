;redcode-94
;name Armadillo
;strategy stone - DJN-controlled bomber with optimized step

ORG 0
ADD.AB #3044, $4
MOV.I $4, @3
DJN.B $-2, $4
MOV.I $2, <1
DAT.F #0, #3044
DAT.F #0, #0
DAT.F #0, #5
