/* MicroJava Instruction Decoder main program  (HM 23-10-02)
   ==========================================
   This is a standalone program that allows you to decode MicroJava object files.
   It invokes the actual decoder in class Decode. The output is written to the
   standard output stream.

   Synopsis: java MJ.Decode <fileName>.obj
-------------------------------------------------------------------------------*/

package MJ;

import java.io.*;
import MJ.CodeGen.Decoder;

public class Decode {

	public static void main(String[] arg) {
		if (arg.length == 0)
			System.out.println("-- no filename specified");
		else {
			try {
				InputStream s = new FileInputStream(arg[0]);
				byte[] code = new byte[8192];
				int len = s.read(code);
				Decoder.decode(code, 14, len - 1);
			} catch (IOException e) {
				System.out.println("-- could not open file " + arg[0]);
			}
		}
	}
}
