# Query plan optimizer build configuration

JAVAC = javac
JAVA = java
SRC_DIR = src
BUILD_DIR = build

SOURCES = $(wildcard $(SRC_DIR)/*.java)

.PHONY: build test clean

build:
	mkdir -p $(BUILD_DIR)
	$(JAVAC) -d $(BUILD_DIR) $(SOURCES)

test: build
	$(JAVAC) -d $(BUILD_DIR) -cp $(BUILD_DIR) /tests/TestRunner.java
	cd $(BUILD_DIR) && $(JAVA) -cp . TestRunner

clean:
	rm -rf $(BUILD_DIR)
