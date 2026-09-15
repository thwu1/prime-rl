package main


type Compiler struct {
	code       string
	codeLength int
	position   int

	instructions []*Instruction
}

func NewCompiler(code string) *Compiler {
	return &Compiler{
		code:         code,
		codeLength:   len(code),
		instructions: []*Instruction{},
	}
}

func (c *Compiler) Compile() []*Instruction {
	loopStack := []int{}

	for c.position < c.codeLength {
		current := c.code[c.position]

		switch current {
		case '[':
			insPos := c.EmitWithArg(JumpIfZero, 0)
			loopStack = append(loopStack, insPos)
		case ']':
			// FIX: Pop from END of stack (LIFO), not front (FIFO)
			openInstruction := loopStack[len(loopStack)-1]
			loopStack = loopStack[:len(loopStack)-1]

			closeInstructionPos := c.EmitWithArg(JumpIfNotZero, openInstruction)
			c.instructions[openInstruction].Argument = closeInstructionPos

		case '+':
			c.CompileFoldableInstruction('+', Plus)
		case '-':
			c.CompileFoldableInstruction('-', Minus)
		case '<':
			c.CompileFoldableInstruction('<', Left)
		case '>':
			c.CompileFoldableInstruction('>', Right)
		case '.':
			c.CompileFoldableInstruction('.', PutChar)
		case ',':
			c.CompileFoldableInstruction(',', ReadChar)
		}

		c.position++
	}

	// Apply peephole optimizations
	c.instructions = c.optimize(c.instructions)

	return c.instructions
}

func (c *Compiler) CompileFoldableInstruction(char byte, insType InsType) {
	count := 1

	for c.position < c.codeLength-1 && c.code[c.position+1] == char {
		count++
		c.position++
	}

	c.EmitWithArg(insType, count)
}

func (c *Compiler) EmitWithArg(insType InsType, arg int) int {
	ins := &Instruction{Type: insType, Argument: arg}
	c.instructions = append(c.instructions, ins)
	return len(c.instructions) - 1
}

// optimize applies peephole optimizations on the compiled instruction stream.
// It detects patterns like [-], [+], [->+++<], [>], [<] and replaces them
// with specialized opcodes.
func (c *Compiler) optimize(instructions []*Instruction) []*Instruction {
	result := make([]*Instruction, 0, len(instructions))

	i := 0
	for i < len(instructions) {
		ins := instructions[i]

		if ins.Type == JumpIfZero {
			// Find the matching JumpIfNotZero
			closePos := ins.Argument
			if closePos < len(instructions) {
				loopBody := instructions[i+1 : closePos]

				// Check for SetZero: [-] or [+]
				if len(loopBody) == 1 &&
					((loopBody[0].Type == Minus && loopBody[0].Argument == 1) ||
						(loopBody[0].Type == Plus && loopBody[0].Argument == 1)) {
					result = append(result, &Instruction{Type: SetZero})
					i = closePos + 1
					continue
				}

				// Check for ScanRight: [>] (single Right(1))
				if len(loopBody) == 1 && loopBody[0].Type == Right && loopBody[0].Argument == 1 {
					result = append(result, &Instruction{Type: ScanRight})
					i = closePos + 1
					continue
				}

				// Check for ScanLeft: [<] (single Left(1))
				if len(loopBody) == 1 && loopBody[0].Type == Left && loopBody[0].Argument == 1 {
					result = append(result, &Instruction{Type: ScanLeft})
					i = closePos + 1
					continue
				}

				// Check for CopyMultiply loop
				if offsets, factors, ok := parseCopyMultiplyLoop(loopBody); ok {
					result = append(result, &Instruction{
						Type:    CopyMultiply,
						Offsets: offsets,
						Factors: factors,
					})
					i = closePos + 1
					continue
				}
			}
		}

		// Not an optimizable pattern; emit as-is but fix jump targets
		result = append(result, ins)
		i++
	}

	// Recompute jump targets after optimization changed instruction indices
	return fixJumpTargets(result)
}

// parseCopyMultiplyLoop checks if a loop body is a copy/multiply pattern.
// A valid copy/multiply loop:
//   - Contains only Plus, Minus, Left, Right instructions
//   - The data pointer returns to its original position (net movement = 0)
//   - The source cell (offset 0) is decremented by exactly 1
//   - Other cells are only incremented/decremented (added to by constant factors)
func parseCopyMultiplyLoop(body []*Instruction) (offsets []int, factors []int, ok bool) {
	// Track the current offset from the starting cell
	currentOffset := 0
	// Map from offset to accumulated factor
	cellChanges := make(map[int]int)

	for _, ins := range body {
		switch ins.Type {
		case Right:
			currentOffset += ins.Argument
		case Left:
			currentOffset -= ins.Argument
		case Plus:
			cellChanges[currentOffset] += ins.Argument
		case Minus:
			cellChanges[currentOffset] -= ins.Argument
		default:
			// Contains non-arithmetic instructions; can't optimize
			return nil, nil, false
		}
	}

	// Data pointer must return to original position
	if currentOffset != 0 {
		return nil, nil, false
	}

	// Source cell (offset 0) must be decremented by exactly 1
	if cellChanges[0] != -1 {
		return nil, nil, false
	}

	// Collect the target offsets and their multiplication factors
	for offset, factor := range cellChanges {
		if offset == 0 {
			continue // Skip the source cell
		}
		offsets = append(offsets, offset)
		factors = append(factors, factor)
	}

	if len(offsets) == 0 {
		return nil, nil, false
	}

	return offsets, factors, true
}

// fixJumpTargets recomputes JumpIfZero/JumpIfNotZero targets after optimization
// has potentially changed instruction positions.
func fixJumpTargets(instructions []*Instruction) []*Instruction {
	// Re-pair the remaining JumpIfZero/JumpIfNotZero instructions
	loopStack := []int{}

	for i, ins := range instructions {
		switch ins.Type {
		case JumpIfZero:
			loopStack = append(loopStack, i)
		case JumpIfNotZero:
			if len(loopStack) > 0 {
				openPos := loopStack[len(loopStack)-1]
				loopStack = loopStack[:len(loopStack)-1]
				instructions[openPos].Argument = i
				instructions[i].Argument = openPos
			}
		}
	}

	return instructions
}
