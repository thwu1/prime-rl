SRCDIR = src
BUILDDIR = build
SOURCES = $(wildcard $(SRCDIR)/*.java)

.PHONY: compile run clean

compile:
	@mkdir -p $(BUILDDIR)
	@javac $(SOURCES) -d $(BUILDDIR)

run: compile
	@if [ -z "$(FILE)" ]; then echo "Usage: make run FILE=<tac-file>" >&2; exit 1; fi
	@java -cp $(BUILDDIR) Main $(FILE)

clean:
	@rm -rf $(BUILDDIR)
