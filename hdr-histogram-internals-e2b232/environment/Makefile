SRCDIR = /app/src
CLASSDIR = /app/build
SOURCES = $(wildcard $(SRCDIR)/*.java)

.PHONY: all build verify clean

all: verify

build: $(SOURCES)
	@mkdir -p $(CLASSDIR)
	javac -d $(CLASSDIR) $<

verify:
	java -cp $(CLASSDIR) HistogramCodec roundtrip

clean:
	rm -rf $(CLASSDIR)
