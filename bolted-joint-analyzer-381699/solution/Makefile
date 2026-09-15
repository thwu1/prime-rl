.PHONY: all clean

all: bjoint
	mkdir -p diagrams

bjoint: src/bjoint.py
	cp src/bjoint.py bjoint
	chmod +x bjoint

clean:
	rm -f bjoint
	rm -rf diagrams analysis.db
