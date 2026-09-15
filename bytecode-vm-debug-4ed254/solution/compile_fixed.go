package main

import "fmt"


// ===== Opcodes =====

type Opcode byte

const (
	OpNop Opcode = iota
	OpPush
	OpPop
	OpTrue
	OpFalse
	OpNil
	OpAdd
	OpSub
	OpMul
	OpDiv
	OpMod
	OpNeg
	OpNot
	OpEq
	OpNeq
	OpLT
	OpGT
	OpLTEq
	OpGTEq
	OpJump
	OpJumpIfTrue
	OpJumpIfFalse
	OpJumpIfNil
	OpJumpIfNotNil
	OpJumpIfEnd
	OpJumpBack
	OpIn
	OpRange
	OpArray
	OpMap
	OpLen
	OpFetch
	OpLoadEnv
	OpBegin
	OpEnd
	OpPointer
	OpGetIndex
	OpGetCount
	OpGetLen
	OpGetAcc
	OpSetAcc
	OpIncrIndex
	OpIncrCount
)

// ===== Program =====

type Program struct {
	Bytecode  []Opcode
	Arguments []int
	Constants []interface{}
}

// ===== Compiler =====

const jumpPlaceholder = 12345

type Compiler struct {
	bytecode  []Opcode
	arguments []int
	constants []interface{}
	constMap  map[interface{}]int
}

func NewCompiler() *Compiler {
	return &Compiler{constMap: make(map[interface{}]int)}
}

func (c *Compiler) Compile(node Node) *Program {
	c.compile(node)
	return &Program{
		Bytecode:  c.bytecode,
		Arguments: c.arguments,
		Constants: c.constants,
	}
}

func (c *Compiler) emit(op Opcode, args ...int) int {
	arg := 0
	if len(args) > 0 {
		arg = args[0]
	}
	c.bytecode = append(c.bytecode, op)
	c.arguments = append(c.arguments, arg)
	return len(c.bytecode)
}

func (c *Compiler) addConst(v interface{}) int {
	switch v.(type) {
	case int, string, bool:
		if idx, ok := c.constMap[v]; ok {
			return idx
		}
	}
	idx := len(c.constants)
	c.constants = append(c.constants, v)
	switch v.(type) {
	case int, string, bool:
		c.constMap[v] = idx
	}
	return idx
}

func (c *Compiler) patchJump(pos int) {
	c.arguments[pos-1] = len(c.bytecode) - pos
}

func (c *Compiler) backJumpDist(target int) int {
	return len(c.bytecode) + 1 - target
}

func (c *Compiler) compile(node Node) {
	switch n := node.(type) {
	case *IntLit:
		c.emit(OpPush, c.addConst(n.Value))
	case *StrLit:
		c.emit(OpPush, c.addConst(n.Value))
	case *BoolLit:
		if n.Value {
			c.emit(OpTrue)
		} else {
			c.emit(OpFalse)
		}
	case *NilLit:
		c.emit(OpNil)
	case *Ident:
		c.emit(OpLoadEnv, c.addConst(n.Name))
	case *Pointer:
		switch n.Name {
		case "":
			c.emit(OpPointer)
		case "acc":
			c.emit(OpGetAcc)
		case "index":
			c.emit(OpGetIndex)
		default:
			panic(fmt.Sprintf("unknown pointer #%s", n.Name))
		}
	case *UnaryExpr:
		c.compile(n.X)
		switch n.Op {
		case "-":
			c.emit(OpNeg)
		case "!":
			c.emit(OpNot)
		}
	case *BinaryExpr:
		c.compileBinary(n)
	case *TernaryExpr:
		c.compile(n.Cond)
		elseBranch := c.emit(OpJumpIfFalse, jumpPlaceholder)
		c.emit(OpPop)
		c.compile(n.Then)
		end := c.emit(OpJump, jumpPlaceholder)
		c.patchJump(elseBranch)
		c.emit(OpPop)
		c.compile(n.Else)
		c.patchJump(end)
	case *ArrayExpr:
		for _, elem := range n.Elems {
			c.compile(elem)
		}
		c.emit(OpPush, c.addConst(len(n.Elems)))
		c.emit(OpArray)
	case *MapExpr:
		for i := range n.Keys {
			c.emit(OpPush, c.addConst(n.Keys[i]))
			c.compile(n.Values[i])
		}
		c.emit(OpPush, c.addConst(len(n.Keys)))
		c.emit(OpMap)
	case *IndexExpr:
		c.compile(n.X)
		c.compile(n.Index)
		c.emit(OpFetch)
	case *CallExpr:
		c.compileCall(n)
	default:
		panic(fmt.Sprintf("compiler: unknown node type %T", node))
	}
}

func (c *Compiler) compileBinary(n *BinaryExpr) {
	switch n.Op {
	case "&&":
		c.compile(n.X)
		end := c.emit(OpJumpIfFalse, jumpPlaceholder)
		c.emit(OpPop)
		c.compile(n.Y)
		c.patchJump(end)
	case "||":
		c.compile(n.X)
		end := c.emit(OpJumpIfTrue, jumpPlaceholder)
		c.emit(OpPop)
		c.compile(n.Y)
		c.patchJump(end)
	case "??":
		c.compile(n.X)
		end := c.emit(OpJumpIfNotNil, jumpPlaceholder)
		c.emit(OpPop)
		c.compile(n.Y)
		c.patchJump(end)
	case "..":
		c.compile(n.X)
		c.compile(n.Y)
		c.emit(OpRange)
	case "in":
		c.compile(n.X)
		c.compile(n.Y)
		c.emit(OpIn)
	default:
		c.compile(n.X)
		c.compile(n.Y)
		switch n.Op {
		case "+":
			c.emit(OpAdd)
		case "-":
			c.emit(OpSub)
		case "*":
			c.emit(OpMul)
		case "/":
			c.emit(OpDiv)
		case "%":
			c.emit(OpMod)
		case "==":
			c.emit(OpEq)
		case "!=":
			c.emit(OpNeq)
		case "<":
			c.emit(OpLT)
		case ">":
			c.emit(OpGT)
		case "<=":
			c.emit(OpLTEq)
		case ">=":
			c.emit(OpGTEq)
		default:
			panic("compiler: unknown binary operator: " + n.Op)
		}
	}
}

func (c *Compiler) compileCall(n *CallExpr) {
	switch n.Name {
	case "len":
		c.compile(n.Args[0])
		c.emit(OpLen)
	case "filter":
		c.compileFilter(n)
	case "map":
		c.compileMapBuiltin(n)
	case "any":
		c.compileAny(n)
	case "all":
		c.compileAll(n)
	case "count":
		c.compileCount(n)
	case "reduce":
		c.compileReduce(n)
	default:
		panic("compiler: unknown function: " + n.Name)
	}
}

func (c *Compiler) compileFilter(n *CallExpr) {
	c.compile(n.Args[0])
	c.emit(OpBegin)
	begin := len(c.bytecode)
	end := c.emit(OpJumpIfEnd, jumpPlaceholder)
	c.compile(n.Args[1])
	noop := c.emit(OpJumpIfFalse, jumpPlaceholder)
	c.emit(OpPop)
	c.emit(OpIncrCount)
	c.emit(OpPointer)
	jmp := c.emit(OpJump, jumpPlaceholder)
	c.patchJump(noop)
	c.emit(OpPop)
	c.patchJump(jmp)
	c.emit(OpIncrIndex)
	c.emit(OpJumpBack, c.backJumpDist(begin))
	c.patchJump(end)
	c.emit(OpGetCount)
	c.emit(OpEnd)
	c.emit(OpArray)
}

func (c *Compiler) compileMapBuiltin(n *CallExpr) {
	c.compile(n.Args[0])
	c.emit(OpBegin)
	begin := len(c.bytecode)
	end := c.emit(OpJumpIfEnd, jumpPlaceholder)
	c.compile(n.Args[1])
	c.emit(OpIncrIndex)
	c.emit(OpJumpBack, c.backJumpDist(begin))
	c.patchJump(end)
	c.emit(OpGetLen)
	c.emit(OpEnd)
	c.emit(OpArray)
}

func (c *Compiler) compileAny(n *CallExpr) {
	c.compile(n.Args[0])
	c.emit(OpBegin)
	begin := len(c.bytecode)
	end := c.emit(OpJumpIfEnd, jumpPlaceholder)
	c.compile(n.Args[1])
	found := c.emit(OpJumpIfTrue, jumpPlaceholder)
	c.emit(OpPop)
	c.emit(OpIncrIndex)
	c.emit(OpJumpBack, c.backJumpDist(begin))
	c.patchJump(end)
	c.emit(OpFalse)
	c.patchJump(found)
	c.emit(OpEnd)
}

func (c *Compiler) compileAll(n *CallExpr) {
	c.compile(n.Args[0])
	c.emit(OpBegin)
	begin := len(c.bytecode)
	end := c.emit(OpJumpIfEnd, jumpPlaceholder)
	c.compile(n.Args[1])
	notAll := c.emit(OpJumpIfFalse, jumpPlaceholder)
	c.emit(OpPop)
	c.emit(OpIncrIndex)
	c.emit(OpJumpBack, c.backJumpDist(begin))
	c.patchJump(end)
	c.emit(OpTrue)
	c.patchJump(notAll)
	c.emit(OpEnd)
}

func (c *Compiler) compileCount(n *CallExpr) {
	c.compile(n.Args[0])
	c.emit(OpBegin)
	begin := len(c.bytecode)
	end := c.emit(OpJumpIfEnd, jumpPlaceholder)
	c.compile(n.Args[1])
	noop := c.emit(OpJumpIfFalse, jumpPlaceholder)
	c.emit(OpPop)
	c.emit(OpIncrCount)
	jmp := c.emit(OpJump, jumpPlaceholder)
	c.patchJump(noop)
	c.emit(OpPop)
	c.patchJump(jmp)
	c.emit(OpIncrIndex)
	c.emit(OpJumpBack, c.backJumpDist(begin))
	c.patchJump(end)
	c.emit(OpGetCount)
	c.emit(OpEnd)
}

func (c *Compiler) compileReduce(n *CallExpr) {
	c.compile(n.Args[0])
	c.emit(OpBegin)
	c.compile(n.Args[2])
	c.emit(OpSetAcc)
	begin := len(c.bytecode)
	end := c.emit(OpJumpIfEnd, jumpPlaceholder)
	c.compile(n.Args[1])
	c.emit(OpSetAcc)
	c.emit(OpIncrIndex)
	c.emit(OpJumpBack, c.backJumpDist(begin))
	c.patchJump(end)
	c.emit(OpGetAcc)
	c.emit(OpEnd)
}
