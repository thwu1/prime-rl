package main

import (
	"encoding/json"
	"fmt"
	"os"
)


func main() {
	disasmMode := len(os.Args) > 1 && os.Args[1] == "--disasm"

	var input struct {
		Expr string                 `json:"expr"`
		Env  map[string]interface{} `json:"env"`
	}
	if err := json.NewDecoder(os.Stdin).Decode(&input); err != nil {
		fmt.Fprintf(os.Stderr, "input error: %v\n", err)
		os.Exit(1)
	}

	if disasmMode {
		output, err := disassembleExpr(input.Expr)
		if err != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", err)
			os.Exit(1)
		}
		fmt.Print(output)
		return
	}

	normalizeEnv(input.Env)

	result, err := evaluate(input.Expr, input.Env)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}

	output := toJSONValue(result)
	data, _ := json.Marshal(output)
	fmt.Println(string(data))
}

func disassembleExpr(exprStr string) (result string, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("%v", r)
		}
	}()
	p := NewParser(exprStr)
	ast := p.Parse()
	c := NewCompiler()
	program := c.Compile(ast)
	return Disassemble(program), nil
}

func evaluate(exprStr string, env map[string]interface{}) (result interface{}, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("%v", r)
		}
	}()
	p := NewParser(exprStr)
	ast := p.Parse()
	c := NewCompiler()
	program := c.Compile(ast)
	vm := &VM{}
	return vm.Run(program, env)
}

func normalizeEnv(env map[string]interface{}) {
	for k, v := range env {
		env[k] = normalizeValue(v)
	}
}

func normalizeValue(v interface{}) interface{} {
	switch x := v.(type) {
	case float64:
		if x == float64(int(x)) && x >= -1e15 && x <= 1e15 {
			return int(x)
		}
		return x
	case []interface{}:
		for i, elem := range x {
			x[i] = normalizeValue(elem)
		}
		return x
	case map[string]interface{}:
		for k, val := range x {
			x[k] = normalizeValue(val)
		}
		return x
	default:
		return v
	}
}

func toJSONValue(v interface{}) interface{} {
	switch x := v.(type) {
	case []int:
		arr := make([]interface{}, len(x))
		for i, n := range x {
			arr[i] = n
		}
		return arr
	case []interface{}:
		arr := make([]interface{}, len(x))
		for i, elem := range x {
			arr[i] = toJSONValue(elem)
		}
		return arr
	case map[string]interface{}:
		m := make(map[string]interface{})
		for k, val := range x {
			m[k] = toJSONValue(val)
		}
		return m
	default:
		return v
	}
}
