COQMAKEFILE = coq_makefile
COQMF = CoqMakefile

all: $(COQMF)
	$(MAKE) -f $(COQMF)

$(COQMF): _CoqProject
	coq_makefile -f _CoqProject -o $(COQMF)

clean:
	if [ -f $(COQMF) ]; then $(MAKE) -f $(COQMF) clean; fi
	rm -f $(COQMF) $(COQMF).conf

.PHONY: all clean
