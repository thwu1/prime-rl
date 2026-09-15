# ChocoPy v2.2 Reference Compiler Output — Data Section
# Generated for program using classes defined in class_defs.py
  .data
  .align 2
  .globl $object$dispatchTable
$object$dispatchTable:
  .word $object.__init__
  .globl $int$dispatchTable
$int$dispatchTable:
  .word $int.__init__
  .globl $bool$dispatchTable
$bool$dispatchTable:
  .word $bool.__init__
  .globl $str$dispatchTable
$str$dispatchTable:
  .word $str.__init__
  .globl $A$dispatchTable
$A$dispatchTable:
  .word $A.__init__
  .word $A.foo
  .word $A.bar
  .globl $C$dispatchTable
$C$dispatchTable:
  .word $C.__init__
  .word $A.foo
  .word $C.bar
  .globl $F$dispatchTable
$F$dispatchTable:
  .word $F.__init__
  .word $F.compute
  .globl $B$dispatchTable
$B$dispatchTable:
  .word $B.__init__
  .word $B.foo
  .word $A.bar
  .word $B.baz
  .globl $G$dispatchTable
$G$dispatchTable:
  .word $G.__init__
  .word $G.compute
  .globl $D$dispatchTable
$D$dispatchTable:
  .word $D.__init__
  .word $B.foo
  .word $A.bar
  .word $B.baz
  .word $D.qux
  .globl $E$dispatchTable
$E$dispatchTable:
  .word $E.__init__
  .word $B.foo
  .word $A.bar
  .word $E.baz
  .globl const_0
const_0:
  .word 3
  .word 5
  .word $str$dispatchTable
  .word 0
  .word 0
  .globl $object$prototype
$object$prototype:
  .word 0
  .word 3
  .word $object$dispatchTable
  .globl $int$prototype
$int$prototype:
  .word 1
  .word 4
  .word $int$dispatchTable
  .word 0
  .globl $bool$prototype
$bool$prototype:
  .word 2
  .word 4
  .word $bool$dispatchTable
  .word 0
  .globl $str$prototype
$str$prototype:
  .word 3
  .word 5
  .word $str$dispatchTable
  .word 0
  .word 0
  .globl $A$prototype
$A$prototype:
  .word 4
  .word 4
  .word $A$dispatchTable
  .word 0
  .globl $C$prototype
$C$prototype:
  .word 5
  .word 5
  .word $C$dispatchTable
  .word 0
  .word const_0
  .globl $F$prototype
$F$prototype:
  .word 6
  .word 4
  .word $F$dispatchTable
  .word 0
  .globl $B$prototype
$B$prototype:
  .word 7
  .word 5
  .word $B$dispatchTable
  .word 0
  .word 0
  .globl $G$prototype
$G$prototype:
  .word 8
  .word 5
  .word $G$dispatchTable
  .word 0
  .word const_0
  .globl $D$prototype
$D$prototype:
  .word 9
  .word 6
  .word $D$dispatchTable
  .word 0
  .word 0
  .word 0
  .globl $E$prototype
$E$prototype:
  .word 10
  .word 5
  .word $E$dispatchTable
  .word 0
  .word 0
  .text
  .globl $object.__init__
  .globl $int.__init__
  .globl $bool.__init__
  .globl $str.__init__
  .globl $A.__init__
  .globl $A.foo
  .globl $A.bar
  .globl $B.__init__
  .globl $B.foo
  .globl $B.baz
  .globl $C.__init__
  .globl $C.bar
  .globl $D.__init__
  .globl $D.qux
  .globl $E.__init__
  .globl $E.baz
  .globl $F.__init__
  .globl $F.compute
  .globl $G.__init__
  .globl $G.compute
