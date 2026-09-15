package main

import "fmt"


// ===== Opcodes =====

type Opcode byte

const (
	OpNop Opcode = iota
	OpPush         // push constants[arg]
	OpPop          // pop top
	OpTrue         // push true
	OpFalse        // push false
	OpNil          // push nil
	OpAdd          // pop b, pop a, push a+b
	OpSub          // pop b, pop a, push a-b
	OpMul          // pop b, pop a, push a*b
	OpDiv          // pop b, pop a, push a/b
	OpMod          // pop b, pop a, push a%b
	OpNeg          // pop a, push -a
	OpNot          // pop a, push !a
	OpEq           // pop b, pop a, push a==b
	OpNeq          // pop b, pop a, push a!=b
	OpLT           // pop b, pop a, push a<b
	OpGT           // pop b, pop a, push a>b
	OpLTEq         // pop b, pop a, push a<=b
	OpGTEq         // pop b, pop a, push a>=b
	OpJump         // ip += arg (relative forward jump)
	OpJumpIfTrue   // if peek is true, ip += arg (does NOT pop)
	OpJumpIfFalse  // if peek is false, ip += arg (does NOT pop)
	OpJumpIfNil    // if peek is nil, ip += arg (does NOT pop)
	OpJumpIfNotNil // if peek is not nil, ip += arg (does NOT pop)
	OpJumpIfEnd    // if scope.Index >= scope.Len, ip += arg
	OpJumpBack     // ip -= arg (relative backward jump)
	OpIn           // pop haystack, pop needle, push needle in haystack
	OpRange        // pop max, pop min, push [min..max] inclusive
	OpArray        // pop size, pop size elements, push array
	OpMap          // pop size, pop size key-value pairs, push map
	OpLen          // pop collection, push len(collection)
	OpFetch        // pop index, pop object, push object[index]
	OpLoadEnv      // push env[constants[arg]]
	OpBegin        // pop iterable, create scope
	OpEnd          // destroy scope
	OpPointer      // push scope current element
	OpGetIndex     // push scope.Index
	OpGetCount     // push scope.Count
	OpGetLen       // push scope.Len
	OpGetAcc       // push scope.Acc
	OpSetAcc       // pop value, set scope.Acc = value
	OpIncrIndex    // scope.Index++
	OpIncrCount    // scope.Count++
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
	return len(c.bytecode) // position AFTER this instruction
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
		elseBranch := c.emit(OpJumpIfTrue, jumpPlaceholder)
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
		end := c.emit(OpJumpIfFalse, jumpPlaceholder)
		c.emit(OpPop)
		c.compile(n.Y)
		c.patchJump(end)
	case "??":
		c.compile(n.X)
		end := c.emit(OpJumpIfNil, jumpPlaceholder)
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
		panic(fmt.Sprintf("compiler: builtin %q not yet implemented", n.Name))
	case "map":
		panic(fmt.Sprintf("compiler: builtin %q not yet implemented", n.Name))
	case "any":
		panic(fmt.Sprintf("compiler: builtin %q not yet implemented", n.Name))
	case "all":
		panic(fmt.Sprintf("compiler: builtin %q not yet implemented", n.Name))
	case "count":
		panic(fmt.Sprintf("compiler: builtin %q not yet implemented", n.Name))
	case "reduce":
		panic(fmt.Sprintf("compiler: builtin %q not yet implemented", n.Name))
	default:
		panic("compiler: unknown function: " + n.Name)
	}
}
