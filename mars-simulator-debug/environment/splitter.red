;redcode-94
;name Hydrant
;strategy hybrid - SPL fork-bomb combined with DAT bomber

ORG 0
SPL.B $0, $0
MOV.I $2, @2
ADD.AB #7, $-1
JMP.A $-2, #0
DAT.F #0, #0
