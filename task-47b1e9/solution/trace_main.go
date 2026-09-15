package main

import (
	"fmt"
	"os"
)

func main() {
	// Enable I/O tracing to capture all WriteAt and Sync calls
	logFile, err := os.Create("/tmp/io_trace.log")
	if err != nil {
		panic(err)
	}
	defer logFile.Close()
	ioTraceWriter = logFile

	// Remove stale database file
	os.Remove("/tmp/trace_test.db")

	db := &KV{Path: "/tmp/trace_test.db"}
	if err := db.Open(); err != nil {
		panic(err)
	}
	for i := 0; i < 15; i++ {
		ioTrace("--- UPDATE %d ---", i)
		key := []byte(fmt.Sprintf("tracekey-%04d", i))
		val := []byte(fmt.Sprintf("traceval-%04d", i))
		if err := db.Set(key, val); err != nil {
			panic(err)
		}
	}
	db.Close()
	ioTraceWriter = nil
	fmt.Println("I/O trace complete. Log written to /tmp/io_trace.log")
}
