package main


type InsType byte

const (
	Plus          InsType = '+'
	Minus         InsType = '-'
	Right         InsType = '>'
	Left          InsType = '<'
	PutChar       InsType = '.'
	ReadChar      InsType = ','
	JumpIfZero    InsType = '['
	JumpIfNotZero InsType = ']'
	// Optimization opcodes
	SetZero      InsType = 'Z'
	CopyMultiply InsType = 'C'
	ScanRight    InsType = 'R'
	ScanLeft     InsType = 'L'
)

type Instruction struct {
	Type     InsType
	Argument int
	// For CopyMultiply: parallel arrays of offsets and factors
	Offsets []int
	Factors []int
}

func InsTypeName(t InsType) string {
	switch t {
	case Plus:
		return "Plus"
	case Minus:
		return "Minus"
	case Right:
		return "Right"
	case Left:
		return "Left"
	case PutChar:
		return "PutChar"
	case ReadChar:
		return "ReadChar"
	case JumpIfZero:
		return "JumpIfZero"
	case JumpIfNotZero:
		return "JumpIfNotZero"
	case SetZero:
		return "SetZero"
	case CopyMultiply:
		return "CopyMultiply"
	case ScanRight:
		return "ScanRight"
	case ScanLeft:
		return "ScanLeft"
	default:
		return string(rune(t))
	}
}
