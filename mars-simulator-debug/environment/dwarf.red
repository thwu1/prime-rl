;redcode-94
;name Dwarf
;author A. K. Dewdney
;strategy stone - bombs every fourth cell with DAT

ORG 1
DAT.F #0, #0
ADD.AB #4, $-1
MOV.I $-2, @-2
JMP.A $-2, #0
