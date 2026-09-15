;redcode
;name PostIncTest
;strategy tests postincrement addressing

ORG 0
MOV.I }2, $4
MOV.I }2, $4
JMP.A $-2, $0
DAT.F $0, $0
DAT.F $0, $0
DAT.F $0, $0
DAT.F $0, $0
