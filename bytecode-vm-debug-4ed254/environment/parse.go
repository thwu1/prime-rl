package main

import (
	"fmt"
	"strconv"
	"strings"
	"unicode"
)


// ===== Token Types =====

type TokenKind int

const (
	tokEOF TokenKind = iota
	tokInt
	tokStr
	tokIdent
	tokTrue
	tokFalse
	tokNil
	tokPlus
	tokMinus
	tokStar
	tokSlash
	tokPercent
	tokEqEq
	tokBangEq
	tokLT
	tokGT
	tokLTEq
	tokGTEq
	tokAmpAmp
	tokPipePipe
	tokBang
	tokQuestion
	tokQuestQuest
	tokColon
	tokDotDot
	tokComma
	tokHash
	tokLParen
	tokRParen
	tokLBrack
	tokRBrack
	tokLBrace
	tokRBrace
	tokIn
)

type Token struct {
	Kind TokenKind
	Str  string
	Num  int
}

// ===== Lexer =====

type Lexer struct {
	input []rune
	pos   int
}

func NewLexer(input string) *Lexer {
	return &Lexer{input: []rune(input), pos: 0}
}

func (l *Lexer) peek() rune {
	if l.pos >= len(l.input) {
		return 0
	}
	return l.input[l.pos]
}

func (l *Lexer) skipWhitespace() {
	for l.pos < len(l.input) && unicode.IsSpace(l.input[l.pos]) {
		l.pos++
	}
}

func (l *Lexer) Scan() Token {
	l.skipWhitespace()
	if l.pos >= len(l.input) {
		return Token{Kind: tokEOF}
	}
	ch := l.input[l.pos]

	if unicode.IsDigit(ch) {
		start := l.pos
		for l.pos < len(l.input) && unicode.IsDigit(l.input[l.pos]) {
			l.pos++
		}
		s := string(l.input[start:l.pos])
		n, _ := strconv.Atoi(s)
		return Token{Kind: tokInt, Num: n, Str: s}
	}

	if ch == '"' {
		l.pos++
		var buf strings.Builder
		for l.pos < len(l.input) && l.input[l.pos] != '"' {
			if l.input[l.pos] == '\\' && l.pos+1 < len(l.input) {
				l.pos++
				switch l.input[l.pos] {
				case 'n':
					buf.WriteByte('\n')
				case 't':
					buf.WriteByte('\t')
				case '\\':
					buf.WriteByte('\\')
				case '"':
					buf.WriteByte('"')
				default:
					buf.WriteRune(l.input[l.pos])
				}
			} else {
				buf.WriteRune(l.input[l.pos])
			}
			l.pos++
		}
		if l.pos < len(l.input) {
			l.pos++
		}
		return Token{Kind: tokStr, Str: buf.String()}
	}

	if unicode.IsLetter(ch) || ch == '_' {
		start := l.pos
		for l.pos < len(l.input) && (unicode.IsLetter(l.input[l.pos]) || unicode.IsDigit(l.input[l.pos]) || l.input[l.pos] == '_') {
			l.pos++
		}
		word := string(l.input[start:l.pos])
		switch word {
		case "true":
			return Token{Kind: tokTrue, Str: word}
		case "false":
			return Token{Kind: tokFalse, Str: word}
		case "nil":
			return Token{Kind: tokNil, Str: word}
		case "in":
			return Token{Kind: tokIn, Str: word}
		default:
			return Token{Kind: tokIdent, Str: word}
		}
	}

	if ch == '#' {
		l.pos++
		if l.pos < len(l.input) && unicode.IsLetter(l.input[l.pos]) {
			start := l.pos
			for l.pos < len(l.input) && (unicode.IsLetter(l.input[l.pos]) || unicode.IsDigit(l.input[l.pos])) {
				l.pos++
			}
			return Token{Kind: tokHash, Str: string(l.input[start:l.pos])}
		}
		return Token{Kind: tokHash, Str: ""}
	}

	l.pos++
	switch ch {
	case '+':
		return Token{Kind: tokPlus, Str: "+"}
	case '-':
		return Token{Kind: tokMinus, Str: "-"}
	case '*':
		return Token{Kind: tokStar, Str: "*"}
	case '/':
		return Token{Kind: tokSlash, Str: "/"}
	case '%':
		return Token{Kind: tokPercent, Str: "%"}
	case '(':
		return Token{Kind: tokLParen, Str: "("}
	case ')':
		return Token{Kind: tokRParen, Str: ")"}
	case '[':
		return Token{Kind: tokLBrack, Str: "["}
	case ']':
		return Token{Kind: tokRBrack, Str: "]"}
	case '{':
		return Token{Kind: tokLBrace, Str: "{"}
	case '}':
		return Token{Kind: tokRBrace, Str: "}"}
	case ',':
		return Token{Kind: tokComma, Str: ","}
	case ':':
		return Token{Kind: tokColon, Str: ":"}
	case '!':
		if l.pos < len(l.input) && l.input[l.pos] == '=' {
			l.pos++
			return Token{Kind: tokBangEq, Str: "!="}
		}
		return Token{Kind: tokBang, Str: "!"}
	case '=':
		if l.pos < len(l.input) && l.input[l.pos] == '=' {
			l.pos++
			return Token{Kind: tokEqEq, Str: "=="}
		}
		panic(fmt.Sprintf("unexpected '=' at position %d", l.pos-1))
	case '<':
		if l.pos < len(l.input) && l.input[l.pos] == '=' {
			l.pos++
			return Token{Kind: tokLTEq, Str: "<="}
		}
		return Token{Kind: tokLT, Str: "<"}
	case '>':
		if l.pos < len(l.input) && l.input[l.pos] == '=' {
			l.pos++
			return Token{Kind: tokGTEq, Str: ">="}
		}
		return Token{Kind: tokGT, Str: ">"}
	case '&':
		if l.pos < len(l.input) && l.input[l.pos] == '&' {
			l.pos++
			return Token{Kind: tokAmpAmp, Str: "&&"}
		}
		panic(fmt.Sprintf("unexpected '&' at position %d", l.pos-1))
	case '|':
		if l.pos < len(l.input) && l.input[l.pos] == '|' {
			l.pos++
			return Token{Kind: tokPipePipe, Str: "||"}
		}
		panic(fmt.Sprintf("unexpected '|' at position %d", l.pos-1))
	case '?':
		if l.pos < len(l.input) && l.input[l.pos] == '?' {
			l.pos++
			return Token{Kind: tokQuestQuest, Str: "??"}
		}
		return Token{Kind: tokQuestion, Str: "?"}
	case '.':
		if l.pos < len(l.input) && l.input[l.pos] == '.' {
			l.pos++
			return Token{Kind: tokDotDot, Str: ".."}
		}
		panic(fmt.Sprintf("unexpected '.' at position %d", l.pos-1))
	}
	panic(fmt.Sprintf("unexpected character '%c' at position %d", ch, l.pos-1))
}

// ===== AST Nodes =====

type Node interface {
	nodeTag()
}

type IntLit struct{ Value int }
type StrLit struct{ Value string }
type BoolLit struct{ Value bool }
type NilLit struct{}
type Ident struct{ Name string }
type Pointer struct{ Name string }
type UnaryExpr struct {
	Op string
	X  Node
}
type BinaryExpr struct {
	Op   string
	X, Y Node
}
type TernaryExpr struct {
	Cond, Then, Else Node
}
type ArrayExpr struct{ Elems []Node }
type MapExpr struct {
	Keys   []string
	Values []Node
}
type IndexExpr struct{ X, Index Node }
type CallExpr struct {
	Name string
	Args []Node
}

func (*IntLit) nodeTag()      {}
func (*StrLit) nodeTag()      {}
func (*BoolLit) nodeTag()     {}
func (*NilLit) nodeTag()      {}
func (*Ident) nodeTag()       {}
func (*Pointer) nodeTag()     {}
func (*UnaryExpr) nodeTag()   {}
func (*BinaryExpr) nodeTag()  {}
func (*TernaryExpr) nodeTag() {}
func (*ArrayExpr) nodeTag()   {}
func (*MapExpr) nodeTag()     {}
func (*IndexExpr) nodeTag()   {}
func (*CallExpr) nodeTag()    {}

// ===== Parser =====

type Parser struct {
	lex     *Lexer
	current Token
}

func NewParser(input string) *Parser {
	p := &Parser{lex: NewLexer(input)}
	p.advance()
	return p
}

func (p *Parser) advance() Token {
	prev := p.current
	p.current = p.lex.Scan()
	return prev
}

func (p *Parser) expect(kind TokenKind) Token {
	if p.current.Kind != kind {
		panic(fmt.Sprintf("parser: expected token kind %d, got %d (%q)", kind, p.current.Kind, p.current.Str))
	}
	return p.advance()
}

func (p *Parser) Parse() Node {
	node := p.parseExpr(0)
	if p.current.Kind != tokEOF {
		panic(fmt.Sprintf("parser: unexpected token %q", p.current.Str))
	}
	return node
}

func infixPrec(kind TokenKind) int {
	switch kind {
	case tokQuestQuest:
		return 10
	case tokPipePipe:
		return 20
	case tokAmpAmp:
		return 30
	case tokEqEq, tokBangEq:
		return 40
	case tokLT, tokGT, tokLTEq, tokGTEq, tokIn:
		return 50
	case tokDotDot:
		return 60
	case tokPlus, tokMinus:
		return 70
	case tokStar, tokSlash, tokPercent:
		return 80
	default:
		return 0
	}
}

func (p *Parser) parseExpr(minPrec int) Node {
	left := p.parsePrimary()

	for {
		if p.current.Kind == tokQuestion && minPrec <= 5 {
			p.advance()
			then := p.parseExpr(0)
			p.expect(tokColon)
			els := p.parseExpr(5)
			left = &TernaryExpr{Cond: left, Then: then, Else: els}
			continue
		}

		if p.current.Kind == tokLBrack {
			p.advance()
			index := p.parseExpr(0)
			p.expect(tokRBrack)
			left = &IndexExpr{X: left, Index: index}
			continue
		}

		prec := infixPrec(p.current.Kind)
		if prec <= minPrec {
			break
		}

		op := p.advance()
		right := p.parseExpr(prec)
		left = &BinaryExpr{Op: op.Str, X: left, Y: right}
	}

	return left
}

func (p *Parser) parsePrimary() Node {
	switch p.current.Kind {
	case tokInt:
		tok := p.advance()
		return &IntLit{Value: tok.Num}
	case tokStr:
		tok := p.advance()
		return &StrLit{Value: tok.Str}
	case tokTrue:
		p.advance()
		return &BoolLit{Value: true}
	case tokFalse:
		p.advance()
		return &BoolLit{Value: false}
	case tokNil:
		p.advance()
		return &NilLit{}
	case tokHash:
		tok := p.advance()
		return &Pointer{Name: tok.Str}
	case tokMinus:
		p.advance()
		x := p.parseUnaryOperand()
		return &UnaryExpr{Op: "-", X: x}
	case tokBang:
		p.advance()
		x := p.parseUnaryOperand()
		return &UnaryExpr{Op: "!", X: x}
	case tokLParen:
		p.advance()
		node := p.parseExpr(0)
		p.expect(tokRParen)
		return node
	case tokLBrack:
		return p.parseArray()
	case tokLBrace:
		return p.parseMap()
	case tokIdent:
		tok := p.advance()
		if p.current.Kind == tokLParen {
			return p.parseCall(tok.Str)
		}
		return &Ident{Name: tok.Str}
	default:
		panic(fmt.Sprintf("parser: unexpected token %q (kind %d)", p.current.Str, p.current.Kind))
	}
}

func (p *Parser) parseUnaryOperand() Node {
	switch p.current.Kind {
	case tokInt:
		tok := p.advance()
		return &IntLit{Value: tok.Num}
	case tokIdent:
		tok := p.advance()
		if p.current.Kind == tokLParen {
			return p.parseCall(tok.Str)
		}
		return &Ident{Name: tok.Str}
	case tokHash:
		tok := p.advance()
		return &Pointer{Name: tok.Str}
	case tokLParen:
		p.advance()
		node := p.parseExpr(0)
		p.expect(tokRParen)
		return node
	case tokMinus:
		p.advance()
		x := p.parseUnaryOperand()
		return &UnaryExpr{Op: "-", X: x}
	case tokBang:
		p.advance()
		x := p.parseUnaryOperand()
		return &UnaryExpr{Op: "!", X: x}
	case tokTrue:
		p.advance()
		return &BoolLit{Value: true}
	case tokFalse:
		p.advance()
		return &BoolLit{Value: false}
	case tokNil:
		p.advance()
		return &NilLit{}
	default:
		panic(fmt.Sprintf("parser: unexpected token after unary operator: %q", p.current.Str))
	}
}

func (p *Parser) parseArray() Node {
	p.expect(tokLBrack)
	var elems []Node
	for p.current.Kind != tokRBrack {
		elems = append(elems, p.parseExpr(0))
		if p.current.Kind == tokComma {
			p.advance()
		}
	}
	p.expect(tokRBrack)
	return &ArrayExpr{Elems: elems}
}

func (p *Parser) parseMap() Node {
	p.expect(tokLBrace)
	var keys []string
	var values []Node
	for p.current.Kind != tokRBrace {
		key := p.expect(tokStr)
		p.expect(tokColon)
		val := p.parseExpr(0)
		keys = append(keys, key.Str)
		values = append(values, val)
		if p.current.Kind == tokComma {
			p.advance()
		}
	}
	p.expect(tokRBrace)
	return &MapExpr{Keys: keys, Values: values}
}

func (p *Parser) parseCall(name string) Node {
	p.expect(tokLParen)
	var args []Node
	for p.current.Kind != tokRParen {
		args = append(args, p.parseExpr(0))
		if p.current.Kind == tokComma {
			p.advance()
		}
	}
	p.expect(tokRParen)
	return &CallExpr{Name: name, Args: args}
}
