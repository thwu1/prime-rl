package main

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: pbcodec <decode|encode|merge> ...\n")
		os.Exit(1)
	}

	cmd := os.Args[1]
	switch cmd {
	case "decode":
		if len(os.Args) != 4 {
			fmt.Fprintf(os.Stderr, "Usage: pbcodec decode <schema.json> <hex>\n")
			os.Exit(1)
		}
		schema, err := LoadSchema(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		data, err := hex.DecodeString(os.Args[3])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: invalid hex: %v\n", err)
			os.Exit(1)
		}
		result, err := Decode(schema, data)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		out, _ := json.MarshalIndent(result, "", "  ")
		fmt.Println(string(out))

	case "encode":
		if len(os.Args) != 4 {
			fmt.Fprintf(os.Stderr, "Usage: pbcodec encode <schema.json> <data.json>\n")
			os.Exit(1)
		}
		schema, err := LoadSchema(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		dataFile, err := os.ReadFile(os.Args[3])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		var values map[string]interface{}
		if err := json.Unmarshal(dataFile, &values); err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		encoded, err := Encode(schema, values)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		fmt.Println(hex.EncodeToString(encoded))

	case "merge":
		if len(os.Args) != 5 {
			fmt.Fprintf(os.Stderr, "Usage: pbcodec merge <schema.json> <hex1> <hex2>\n")
			os.Exit(1)
		}
		schema, err := LoadSchema(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		data1, err := hex.DecodeString(os.Args[3])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: invalid hex: %v\n", err)
			os.Exit(1)
		}
		data2, err := hex.DecodeString(os.Args[4])
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: invalid hex: %v\n", err)
			os.Exit(1)
		}
		msg1, err := Decode(schema, data1)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error decoding first message: %v\n", err)
			os.Exit(1)
		}
		msg2, err := Decode(schema, data2)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error decoding second message: %v\n", err)
			os.Exit(1)
		}
		merged := Merge(schema, msg1, msg2)
		out, _ := json.MarshalIndent(merged, "", "  ")
		fmt.Println(string(out))

	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", cmd)
		os.Exit(1)
	}
}
