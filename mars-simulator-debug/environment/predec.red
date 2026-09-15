;redcode
;name PreDecTest
;strategy tests predecrement addressing

ORG 0
MOV.I $3, <2
JMP.A $-1, $0
DAT.F $0, $5
DAT.F $0, $0
DAT.F $0, $0
DAT.F $0, $0
DAT.F $0, $0
