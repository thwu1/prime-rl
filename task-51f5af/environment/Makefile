CC := gcc

PROGRAMS := simple multi cond loop call call_live spill nested loop_call fib

.SUFFIXES:
.PHONY: all clean

all: $(PROGRAMS)

runtime.o: runtime.c
	$(CC) -c -o $@ $<

%.s: compile_driver.py allocator.py codegen.py programs.py x86_ast.py
	python3 compile_driver.py $* $@

$(PROGRAMS): %: %.s runtime.o
	$(CC) -no-pie -o $@ $< runtime.o

clean:
	rm -f *.s *.o $(PROGRAMS)
