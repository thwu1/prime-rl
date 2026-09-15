# generic UNIX makefile
CC = gcc			# req. for linux
#CC = cc				# if you don't have gcc
# Configuration options:
#
# No.   Name            Incompatible with   Description
# (1)   -DSERVER        2, 6, 7             disables cdb debugger (koth server 
#                                           version)
# (2)   -DGRAPHX        1                   enables platform specific core 
#                                           graphics
# (3)   -DKEYPRESS                          only for curses display on SysV:
#                                           enter cdb upon keypress (use if
#                                           Ctrl-C doesn't work)
# (4)   -DEXT94                             ICWS'94 + SEQ,SNE,NOP,*,{,}
# (5)   -DSMALLMEM                          16-bit addresses, less memory
# (6)   -DXWINGRAPHX    1                   X-Windows graphics (UNIX)
# (7)   -DCURSESGRAPHX  1                   Curses display (UNIX)
# (8)   -DPERMUTATE                         enables -P switch
# (9)   -DRWLIMIT                           enables read/write limits
# (10)  -DSAFECOLORS                        use Okabe-Ito CVD-safe palette

CFLAGS = -O2 -DEXT94 -DSERVER -DPERMUTATE -DRWLIMIT
LFLAGS += -x
# LIB = -lncurses			# enable this one for curses display
# LIB = -lvgagl -lvga			# enable this one for Linux/SVGA
LIB =

.SUFFIXES: .o .c .c~ .man .doc .6
MAINFILE = pmars

HEADER = global.h config.h asm.h sim.h 
OBJ1 = pmars.o asm.o eval.o disasm.o cdb.o sim.o pos.o
OBJ2 = clparse.o global.o token.o 
OBJ3 = str_eng.o

all: flags $(MAINFILE)

flags:
	@echo Making $(MAINFILE) with compiler flags $(CFLAGS)

$(MAINFILE): $(OBJ1) $(OBJ2) $(OBJ3)
	@echo Linking $(MAINFILE)
	@$(CC) $(LDFLAGS) -o $(MAINFILE) $(OBJ1) $(OBJ2) $(OBJ3) $(LIB)
	@strip $(MAINFILE)
	@echo done

token.o asm.o disasm.o: asm.h

sim.o cdb.o pos.o disasm.o: sim.h

sim.o: curdisp.c uidisp.c lnxdisp.c xwindisp.c

xwindisp.c: xwindisp.h pmarsicn.h

lnxdisp.c: lnxdisp.h

$(OBJ1) $(OBJ2) $(OBJ3): Makefile config.h global.h

.c.o:
	@echo Compiling $*.o 
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $*.c

clean:
	rm -f $(OBJ1) $(OBJ2) $(OBJ3) core

