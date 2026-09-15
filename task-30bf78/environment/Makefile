ANTLR4_JAR := /usr/local/lib/antlr-4.13.2-complete.jar
GRAMMAR := Lox.g4
OUTPUT_DIR := gen

.PHONY: generate clean

generate: $(GRAMMAR)
	java -jar $(ANTLR4_JAR) -Dlanguage=Python3 -visitor -no-listener -o $(OUTPUT_DIR) $(GRAMMAR)
	touch $(OUTPUT_DIR)/__init__.py

clean:
	rm -rf $(OUTPUT_DIR)
