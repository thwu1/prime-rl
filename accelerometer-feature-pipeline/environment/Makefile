# Accelerometer data processing pipeline
# Build: make compile
# Full pipeline: make pipeline

SRCDIR  = /app/source
BINDIR  = /app/bin
JAVAC   = javac -encoding UTF-8
JAVA    = java

SOURCES := $(wildcard $(SRCDIR)/*.java)

.PHONY: all compile pipeline clean

all: compile

compile:
	@mkdir -p $(BINDIR)
	$(JAVAC) -d $(BINDIR) $(SOURCES)

pipeline: compile
	@mkdir -p /app/data /app/output
	$(JAVA) -cp $(BINDIR) CalibratorMain /app/data/input.csv /app/config/calibration.properties /app/data/calibrated.csv
	$(JAVA) -cp $(BINDIR) EpochFeatureExtractor /app/data/calibrated.csv /app/output/features.json

clean:
	rm -rf $(BINDIR) /app/data/calibrated.csv /app/output/
