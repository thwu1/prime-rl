/* MicroJava Instruction Decoder  (HM 23-10-02)
   =============================
   Decodes (a range of) the code buffer and writes it to the standard output stream.
----------------------------------------------------------------------------------*/

package MJ.CodeGen;

public class Decoder {

	private static final int  // instruction codes
		load        =  1,
		load0       =  2,
		load1       =  3,
		load2       =  4,
		load3       =  5,
		store       =  6,
		store0      =  7,
		store1      =  8,
		store2      =  9,
		store3      = 10,
		getstatic   = 11,
		putstatic   = 12,
		getfield    = 13,
		putfield    = 14,
		const0      = 15,
		const1      = 16,
		const2      = 17,
		const3      = 18,
		const4      = 19,
		const5      = 20,
		const_m1    = 21,
		const_      = 22,
		add         = 23,
		sub         = 24,
		mul         = 25,
		div         = 26,
		rem         = 27,
		neg         = 28,
		shl         = 29,
		shr         = 30,
		inc         = 31,
		new_        = 32,
		newarray    = 33,
		aload       = 34,
		astore      = 35,
		baload      = 36,
		bastore     = 37,
		arraylength = 38,
		pop         = 39,
		dup         = 40,
		dup2        = 41,
		jmp         = 42,
		jeq         = 43,
		jne         = 44,
		jlt         = 45,
		jle         = 46,
		jgt         = 47,
		jge         = 48,
		call        = 49,
		return_     = 50,
		enter       = 51,
		exit        = 52,
		read        = 53,
		print       = 54,
		bread       = 55,
		bprint      = 56,
		trap		    = 57;

	private static byte[] code;	// code buffer
	private static int cur;			// address of next byte to decode
	private static int adr;			// address of currently decoded instruction

	// Reads and returns the next byte from the code buffer (unsigned)
	private static int get() {
		return ((int)code[cur++]) << 24 >>> 24;
	}

	// Reads and returns the next 2 bytes from the code buffer (signed)
	private static int get2() {
		return (get() * 256 + get()) << 16 >> 16;
	}

	// Reads and returns the next 4 bytes from the code buffer (signed)
	private static int get4() {
		return (get2() << 16) + (get2() << 16 >>> 16);
	}

	// Prints an instruction
	private static void P(String s) {
		System.out.println(adr + ": " + s);
		adr = cur;
	}

	// Decodes the range code[beg..end] of the code buffer
	public static void decode(byte[] code, int beg, int end) {
		Decoder.code = code;
		cur = beg;
		adr = cur;
		while (cur <= end) {
			switch(get()) {
				case load:      P("load " + get()); break;
				case load0:     P("load0"); break;
				case load1:     P("load1"); break;
				case load2:     P("load2"); break;
				case load3:     P("load3"); break;
				case store:     P("store " + get()); break;
				case store0:    P("store0"); break;
				case store1:    P("store1"); break;
				case store2:    P("store2"); break;
				case store3:    P("store3"); break;
				case getstatic: P("getstatic " + get2()); break;
				case putstatic: P("putstatic " + get2()); break;
				case getfield:  P("getfield " + get2()); break;
				case putfield:  P("putfield " + get2()); break;
				case const0:    P("const0"); break;
				case const1:    P("const1"); break;
				case const2:    P("const2"); break;
				case const3:    P("const3"); break;
				case const4:    P("const4"); break;
				case const5:    P("const5"); break;
				case const_m1:  P("const_m1"); break;
				case const_:    P("const "+get4()); break;
				case add:       P("add"); break;
				case sub:       P("sub"); break;
				case mul:       P("mul"); break;
				case div:       P("div"); break;
				case rem:       P("rem"); break;
				case neg:       P("neg"); break;
				case shl:       P("shl"); break;
				case shr:       P("shr"); break;
				case inc:       P("inc " + get() + " " + (get() << 24 >> 24)); break;
				case new_:      P("new " + get2()); break;
				case newarray:  P("newarray " + get()); break;
				case aload:     P("aload"); break;
				case astore:    P("astore"); break;
				case baload:    P("baload"); break;
				case bastore:   P("bastore"); break;
				case arraylength: P("arraylength"); break;
				case pop:       P("pop"); break;
				case dup:       P("dup"); break;
				case dup2:      P("dup2"); break;
				case jmp:       P("jmp " + get2()); break;
				case jeq:       P("jeq " + get2()); break;
				case jne:       P("jne " + get2()); break;
				case jlt:       P("jlt " + get2()); break;
				case jle:       P("jle " + get2()); break;
				case jgt:       P("jgt " + get2()); break;
				case jge:       P("jge " + get2()); break;
				case call:      P("call " + get2()); break;
				case return_:   P("return"); break;
				case enter:     P("enter " + get() + " " + get()); break;
				case exit:      P("exit"); break;
				case read:      P("read"); break;
				case print:     P("print"); break;
				case bread:     P("bread"); break;
				case bprint:    P("bprint"); break;
				case trap:      P("trap " + get()); break;
				default:        P("-- error--"); break;
			}
		}
	}
}