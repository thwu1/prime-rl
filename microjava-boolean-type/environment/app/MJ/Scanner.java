/* MicroJava Scanner (HM 23-10-02)
   =================
---------------------------------------------------------------------*/

package MJ;
import java.io.*;

public class Scanner {
	private static final char eofCh = (char)-1;
	private static final char eol = '\n';

	private static final int  // token codes
		none      = 0,  // error token
		ident     = 1,  // identifier
		number    = 2,  // number
		charCon   = 3,  // character constant
		plus      = 4,  // +
		minus     = 5,  // -
		times     = 6,  // *
		slash     = 7,  // /
		rem       = 8,  // %
		pplus     = 9,  // ++
		mminus    = 10, // --
		eql       = 11, // ==
		neq       = 12, // !=
		lss       = 13, // <
		leq       = 14, // <=
		gtr       = 15, // >
		geq       = 16, // >=
		and       = 17, // &&
		or        = 18, // ||
		lpar      = 19, // (
		rpar      = 20, // )
		lbrack    = 21, // [
		rbrack    = 22, // ]
		lbrace    = 23, // {
		rbrace    = 24, // }
		assign    = 25, // =
		semicolon = 26, // ;
		comma     = 27, // ,
		period    = 28, // .
		break_    = 29, // ... keywords ...
		class_    = 30,
		else_     = 31,
		final_    = 32,
		if_       = 33,
		new_      = 34,
		print_    = 35,
		program_  = 36,
		read_     = 37,
		return_   = 38,
		void_     = 39,
		while_    = 40,
		eof       = 41; // end-of-file token

	private static final String key[] = { // sorted list of keywords
		"break", "class", "else", "final", "if", "new", "print",
		"program", "read", "return", "void", "while"
	};
	private static final int keyVal[] = { // token codes for keywords
		break_, class_, else_, final_, if_, new_, print_,
		program_, read_, return_, void_, while_
	};

	private static char   ch;		// lookahead character
	private static int    col;	// current column
	private static int    line;	// current line
	private static Reader in;  	// source file reader
	private static char[] lex;	// current lexeme (token string)

	// Forwards the error message to the parser which adds a line and a column number
	private static void error(String msg) {
		Parser.error(msg);
	}

	// ch = next input character
	private static void nextCh() {
		try {
			ch = (char)in.read(); col++;
			if (ch == eol) {line++; col = 0;}
		} catch (IOException e) {
			ch = eofCh;
		}
	}

	// Initializes the scanner
	public static void init(Reader r) {
		in = new BufferedReader(r);
		lex = new char[128];
		line = 1; col = 0;
		nextCh();
	}

	// Returns the next input token
	public static Token next() {
		while (ch <= ' ') nextCh(); // skip white space
		Token t = new Token();
		t.line = line; t.col = col;
		switch (ch) {
			// ident or keyword
			case 'a': case 'b': case 'c': case 'd': case 'e': case 'f':
			case 'g': case 'h': case 'i': case 'j': case 'k': case 'l':
			case 'm': case 'n': case 'o': case 'p': case 'q': case 'r':
			case 's': case 't': case 'u': case 'v': case 'w': case 'x':
			case 'y': case 'z': case 'A': case 'B': case 'C': case 'D':
			case 'E': case 'F': case 'G': case 'H': case 'I': case 'J':
			case 'K': case 'L': case 'M': case 'N': case 'O': case 'P':
			case 'Q': case 'R': case 'S': case 'T': case 'U': case 'V':
			case 'W': case 'X': case 'Y': case 'Z':
				readName(t);
				break;

			// number
			case '0': case '1': case '2': case '3': case '4': case '5':
			case '6': case '7': case '8': case '9':
				readNumber(t);
				break;

			// character constant
			case '\'':
				readCharCon(t);
				break;

			// operators and special characters
			case '+':
				nextCh();
				if (ch == '+') {t.kind = pplus; nextCh();}
				else t.kind = plus;
				break;
			case '-':
				nextCh();
				if (ch == '-') {t.kind = mminus; nextCh();}
				else t.kind = minus;
				break;
			case '*':
				t.kind = times; nextCh();
				break;
			case '/':
				nextCh();
				if (ch == '/') {
					do nextCh(); while (ch != eol && ch != eofCh);
					t = next();
				} else t.kind = slash;
				break;
			case '%':
				t.kind = rem; nextCh();
				break;
			case '=':
				nextCh();
				if (ch == '=') { t.kind = eql; nextCh(); }
				else t.kind = assign;
				break;
			case '!':
				nextCh();
				if (ch == '=') { t.kind = neq; nextCh(); }
				else t.kind = none;
				break;
			case '<':
				nextCh();
				if (ch == '=') { t.kind = leq; nextCh(); }
				else t.kind = lss;
				break;
			case '>':
				nextCh();
				if (ch == '=') { t.kind = geq; nextCh(); }
				else t.kind = gtr;
				break;
			case '&':
				nextCh();
				if (ch == '&') { t.kind = and; nextCh(); }
				else t.kind = none;
				break;
			case '|':
				nextCh();
				if (ch == '|') { t.kind = or; nextCh(); }
				else t.kind = none;
				break;
			case ';':
				t.kind = semicolon; nextCh();
				break;
			case ',':
				t.kind = comma; nextCh();
				break;
			case '.':
				t.kind = period; nextCh();
				break;
			case '(':
				t.kind = lpar; nextCh();
				break;
			case ')':
				t.kind = rpar; nextCh();
				break;
			case '[':
				t.kind = lbrack; nextCh();
				break;
			case ']':
				t.kind = rbrack; nextCh();
				break;
			case '{':
				t.kind = lbrace; nextCh();
				break;
			case '}':
				t.kind = rbrace; nextCh();
				break;
			case eofCh:
				t.kind = eof;
				break;
			default:
				t.kind = none; nextCh();
				break;
		}
		return t;
	}

	// Returns ident or the token number of a keyword
	private static int checkIfKeyword (String s) {
		int i = 0, j = key.length-1, k, d;
		while (i <= j) {
			k = (i + j) / 2;
			d = s.compareTo(key[k]);
			if (d < 0) j = k - 1;
			else if (d > 0) i = k + 1;
			else return keyVal[k];
		}
		return ident;
	}

	// Scans an identifier; ch holds its first letter
	private static void readName(Token t) {
		int i = 0;
		do {
			lex[i++] = ch; nextCh();
		} while ('a' <= ch && ch <= 'z' || 'A' <= ch && ch <= 'Z'
				|| '0' <= ch && ch <= '9' || ch == '_');
		t.val = new String(lex, 0, i);
		t.kind = checkIfKeyword(t.val);
	}

	// Scans a number; ch holds its first digit
	private static void readNumber(Token t) {
		int i = 0;
		do {
			lex[i++] = ch; nextCh();
		} while ('0' <= ch && ch <= '9');
		t.kind = number;
		t.val = new String(lex, 0, i);
		try {
			t.numVal = Integer.parseInt(t.val);
		} catch (NumberFormatException e) {
			t.numVal = 0;
			error("number too large");
		}
	}

	// Scans a character constant; ch hold the opening apostroph
	private static void readCharCon(Token t) {
		int i = 0;
		t.kind = charCon;
		nextCh();
		while (ch != '\'' && ch != eol && ch != eofCh) {
			lex[i++] = ch; nextCh();
		}
		if (ch == eol || ch == eofCh) {
			error("invalid character constant");
		} else if (i == 1 && lex[0] != '\\') {
			t.numVal = lex[0];
		} else if (i == 2 && lex[0] == '\\') {
			if      (lex[1] == 'r') t.numVal = '\r';
			else if (lex[1] == 'n') t.numVal = '\n';
			else if (lex[1] == 't') t.numVal = '\t';
			else error("invalid character constant");
		} else error("invalid character constant");
		if (ch == '\'') nextCh();
	}
}
