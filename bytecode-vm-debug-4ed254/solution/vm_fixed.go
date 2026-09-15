package main

import (
	"fmt"
	"reflect"
)


// ===== Scope =====

type Scope struct {
	Array []interface{}
	Ints  []int
	Index int
	Len   int
	Count int
	Acc   interface{}
}

func (s *Scope) Item() interface{} {
	if s.Ints != nil {
		return s.Ints[s.Index]
	}
	return s.Array[s.Index]
}

// ===== VM =====

type VM struct {
	stack     []interface{}
	scopes    []*Scope
	currScope *Scope
	ip        int
}

func (vm *VM) Run(prog *Program, env map[string]interface{}) (interface{}, error) {
	vm.stack = vm.stack[:0]
	vm.scopes = vm.scopes[:0]
	vm.currScope = nil
	vm.ip = 0

	for vm.ip < len(prog.Bytecode) {
		op := prog.Bytecode[vm.ip]
		arg := prog.Arguments[vm.ip]
		vm.ip++

		switch op {
		case OpPush:
			vm.push(prog.Constants[arg])
		case OpPop:
			vm.pop()
		case OpTrue:
			vm.push(true)
		case OpFalse:
			vm.push(false)
		case OpNil:
			vm.push(nil)

		case OpAdd:
			b, a := vm.pop(), vm.pop()
			vm.push(add(a, b))
		case OpSub:
			b, a := vm.pop(), vm.pop()
			vm.push(sub(a, b))
		case OpMul:
			b, a := vm.pop(), vm.pop()
			vm.push(mul(a, b))
		case OpDiv:
			b, a := vm.pop(), vm.pop()
			vm.push(div(a, b))
		case OpMod:
			b, a := vm.pop(), vm.pop()
			vm.push(mod(a, b))
		case OpNeg:
			vm.push(neg(vm.pop()))
		case OpNot:
			vm.push(!vm.pop().(bool))

		case OpEq:
			b, a := vm.pop(), vm.pop()
			vm.push(equal(a, b))
		case OpNeq:
			b, a := vm.pop(), vm.pop()
			vm.push(!equal(a, b))
		case OpLT:
			b, a := vm.pop(), vm.pop()
			vm.push(less(a, b))
		case OpGT:
			b, a := vm.pop(), vm.pop()
			vm.push(less(b, a))
		case OpLTEq:
			b, a := vm.pop(), vm.pop()
			vm.push(!less(b, a))
		case OpGTEq:
			b, a := vm.pop(), vm.pop()
			vm.push(!less(a, b))

		case OpJump:
			vm.ip += arg

		case OpJumpIfTrue:
			if vm.current().(bool) {
				vm.ip += arg
			}

		case OpJumpIfFalse:
			if !vm.current().(bool) {
				vm.ip += arg
			}

		case OpJumpIfNil:
			if vm.current() == nil {
				vm.ip += arg
			}

		case OpJumpIfNotNil:
			if vm.current() != nil {
				vm.ip += arg
			}

		case OpJumpIfEnd:
			if vm.currScope.Index >= vm.currScope.Len {
				vm.ip += arg
			}

		case OpJumpBack:
			vm.ip -= arg

		case OpIn:
			b, a := vm.pop(), vm.pop()
			vm.push(contains(a, b))

		case OpRange:
			b, a := vm.pop(), vm.pop()
			lo := toInt(a)
			hi := toInt(b)
			size := hi - lo + 1
			if size < 0 {
				size = 0
			}
			r := make([]int, size)
			for i := range r {
				r[i] = lo + i
			}
			vm.push(r)

		case OpArray:
			size := vm.pop().(int)
			arr := make([]interface{}, size)
			for i := size - 1; i >= 0; i-- {
				arr[i] = vm.pop()
			}
			vm.push(arr)

		case OpMap:
			size := vm.pop().(int)
			m := make(map[string]interface{})
			for i := 0; i < size; i++ {
				val := vm.pop()
				key := vm.pop().(string)
				m[key] = val
			}
			vm.push(m)

		case OpLen:
			vm.push(length(vm.pop()))

		case OpFetch:
			idx := vm.pop()
			obj := vm.pop()
			vm.push(fetch(obj, idx))

		case OpLoadEnv:
			name := prog.Constants[arg].(string)
			vm.push(env[name])

		case OpBegin:
			a := vm.pop()
			s := &Scope{}
			switch v := a.(type) {
			case []interface{}:
				s.Array = v
				s.Len = len(v)
			case []int:
				s.Ints = v
				s.Len = len(v)
			}
			vm.scopes = append(vm.scopes, s)
			vm.currScope = s

		case OpEnd:
			vm.scopes = vm.scopes[:len(vm.scopes)-1]
			if len(vm.scopes) > 0 {
				vm.currScope = vm.scopes[len(vm.scopes)-1]
			} else {
				vm.currScope = nil
			}

		case OpPointer:
			vm.push(vm.currScope.Item())

		case OpGetIndex:
			vm.push(vm.currScope.Index)
		case OpGetCount:
			vm.push(vm.currScope.Count)
		case OpGetLen:
			vm.push(vm.currScope.Len)
		case OpGetAcc:
			vm.push(vm.currScope.Acc)

		case OpSetAcc:
			vm.currScope.Acc = vm.pop()

		case OpIncrIndex:
			vm.currScope.Index++
		case OpIncrCount:
			vm.currScope.Count++

		default:
			panic(fmt.Sprintf("vm: unknown opcode %d", op))
		}
	}

	if len(vm.stack) > 0 {
		return vm.pop(), nil
	}
	return nil, nil
}

func (vm *VM) push(v interface{}) {
	vm.stack = append(vm.stack, v)
}

func (vm *VM) pop() interface{} {
	n := len(vm.stack)
	v := vm.stack[n-1]
	vm.stack[n-1] = nil
	vm.stack = vm.stack[:n-1]
	return v
}

func (vm *VM) current() interface{} {
	return vm.stack[len(vm.stack)-1]
}

// ===== Runtime Helpers =====

func toInt(v interface{}) int {
	switch x := v.(type) {
	case int:
		return x
	case float64:
		return int(x)
	default:
		panic(fmt.Sprintf("cannot convert %T to int", v))
	}
}

func add(a, b interface{}) interface{} {
	switch x := a.(type) {
	case int:
		return x + toInt(b)
	case string:
		return x + b.(string)
	default:
		panic(fmt.Sprintf("cannot add %T and %T", a, b))
	}
}

func sub(a, b interface{}) interface{} {
	return toInt(a) - toInt(b)
}

func mul(a, b interface{}) interface{} {
	return toInt(a) * toInt(b)
}

func div(a, b interface{}) interface{} {
	return toInt(a) / toInt(b)
}

func mod(a, b interface{}) interface{} {
	return toInt(a) % toInt(b)
}

func neg(a interface{}) interface{} {
	return -toInt(a)
}

func equal(a, b interface{}) bool {
	return reflect.DeepEqual(a, b)
}

func less(a, b interface{}) bool {
	switch x := a.(type) {
	case int:
		return x < toInt(b)
	case string:
		return x < b.(string)
	default:
		panic(fmt.Sprintf("cannot compare %T and %T", a, b))
	}
}

func contains(needle, haystack interface{}) bool {
	switch h := haystack.(type) {
	case []interface{}:
		for _, v := range h {
			if equal(needle, v) {
				return true
			}
		}
		return false
	case []int:
		n := toInt(needle)
		for _, v := range h {
			if v == n {
				return true
			}
		}
		return false
	case map[string]interface{}:
		key, ok := needle.(string)
		if !ok {
			return false
		}
		_, exists := h[key]
		return exists
	default:
		return false
	}
}

func fetch(obj, idx interface{}) interface{} {
	switch o := obj.(type) {
	case []interface{}:
		return o[toInt(idx)]
	case []int:
		return o[toInt(idx)]
	case map[string]interface{}:
		return o[idx.(string)]
	default:
		panic(fmt.Sprintf("cannot index %T with %T", obj, idx))
	}
}

func length(a interface{}) int {
	switch v := a.(type) {
	case []interface{}:
		return len(v)
	case []int:
		return len(v)
	case string:
		return len(v)
	case map[string]interface{}:
		return len(v)
	default:
		panic(fmt.Sprintf("cannot get length of %T", a))
	}
}
