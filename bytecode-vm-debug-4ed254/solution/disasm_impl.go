package main

import "fmt"


var opcodeNames = map[Opcode]string{
	OpNop:          "OpNop",
	OpPush:         "OpPush",
	OpPop:          "OpPop",
	OpTrue:         "OpTrue",
	OpFalse:        "OpFalse",
	OpNil:          "OpNil",
	OpAdd:          "OpAdd",
	OpSub:          "OpSub",
	OpMul:          "OpMul",
	OpDiv:          "OpDiv",
	OpMod:          "OpMod",
	OpNeg:          "OpNeg",
	OpNot:          "OpNot",
	OpEq:           "OpEq",
	OpNeq:          "OpNeq",
	OpLT:           "OpLT",
	OpGT:           "OpGT",
	OpLTEq:         "OpLTEq",
	OpGTEq:         "OpGTEq",
	OpJump:         "OpJump",
	OpJumpIfTrue:   "OpJumpIfTrue",
	OpJumpIfFalse:  "OpJumpIfFalse",
	OpJumpIfNil:    "OpJumpIfNil",
	OpJumpIfNotNil: "OpJumpIfNotNil",
	OpJumpIfEnd:    "OpJumpIfEnd",
	OpJumpBack:     "OpJumpBack",
	OpIn:           "OpIn",
	OpRange:        "OpRange",
	OpArray:        "OpArray",
	OpMap:          "OpMap",
	OpLen:          "OpLen",
	OpFetch:        "OpFetch",
	OpLoadEnv:      "OpLoadEnv",
	OpBegin:        "OpBegin",
	OpEnd:          "OpEnd",
	OpPointer:      "OpPointer",
	OpGetIndex:     "OpGetIndex",
	OpGetCount:     "OpGetCount",
	OpGetLen:       "OpGetLen",
	OpGetAcc:       "OpGetAcc",
	OpSetAcc:       "OpSetAcc",
	OpIncrIndex:    "OpIncrIndex",
	OpIncrCount:    "OpIncrCount",
}

func Disassemble(prog *Program) string {
	var result string
	for i := 0; i < len(prog.Bytecode); i++ {
		op := prog.Bytecode[i]
		arg := prog.Arguments[i]
		name, ok := opcodeNames[op]
		if !ok {
			name = fmt.Sprintf("Unknown(%d)", op)
		}

		switch op {
		case OpPush, OpLoadEnv:
			if arg >= 0 && arg < len(prog.Constants) {
				val := prog.Constants[arg]
				var valStr string
				if s, ok := val.(string); ok {
					valStr = fmt.Sprintf("%q", s)
				} else {
					valStr = fmt.Sprintf("%v", val)
				}
				result += fmt.Sprintf("%04d %-16s %d    ; %s\n", i, name, arg, valStr)
			} else {
				result += fmt.Sprintf("%04d %-16s %d\n", i, name, arg)
			}
		default:
			result += fmt.Sprintf("%04d %-16s %d\n", i, name, arg)
		}
	}
	return result
}
