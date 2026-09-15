package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
)

// Prefix represents an IP prefix in the BYOIP system
type Prefix struct {
	ID             int    `json:"id"`
	CIDR           string `json:"cidr"`
	CustomerID     string `json:"customer_id"`
	Status         string `json:"status"`
	ServiceBinding string `json:"service_binding"`
}

// PrefixStore manages prefix data backed by a JSON file
type PrefixStore struct {
	Prefixes []Prefix
	DataFile string
}

// NewPrefixStore loads prefix data from a JSON file
func NewPrefixStore(dataFile string) (*PrefixStore, error) {
	data, err := os.ReadFile(dataFile)
	if err != nil {
		return nil, fmt.Errorf("reading prefix data: %w", err)
	}
	var prefixes []Prefix
	if err := json.Unmarshal(data, &prefixes); err != nil {
		return nil, fmt.Errorf("parsing prefix data: %w", err)
	}
	return &PrefixStore{Prefixes: prefixes, DataFile: dataFile}, nil
}

// Save writes the current prefix state back to the data file
func (ps *PrefixStore) Save() error {
	data, err := json.MarshalIndent(ps.Prefixes, "", "  ")
	if err != nil {
		return fmt.Errorf("marshaling prefix data: %w", err)
	}
	return os.WriteFile(ps.DataFile, data, 0644)
}

// FetchPrefixes returns prefixes filtered by query parameters.
// When pending_delete is specified, only pending deletion prefixes are returned.
func (ps *PrefixStore) FetchPrefixes(queryString string) []Prefix {
	params, _ := url.ParseQuery(queryString)

	// Fix: Use Has() to correctly detect valueless query parameters
	// like ?pending_delete (without =value). Get() returns empty string
	// for such parameters, which would incorrectly fall through.
	if params.Has("pending_delete") {
		var pending []Prefix
		for _, p := range ps.Prefixes {
			if p.Status == "pending_delete" {
				pending = append(pending, p)
			}
		}
		return pending
	}

	return ps.Prefixes
}

// CleanupPrefixes removes prefixes that are pending deletion.
// Includes a circuit breaker that refuses to delete more than 50% of
// total prefixes in a single run to prevent cascading data loss.
func (ps *PrefixStore) CleanupPrefixes(queryString string) (int, error) {
	toDelete := ps.FetchPrefixes(queryString)

	// Circuit breaker: refuse to delete more than 50% of total prefixes
	total := len(ps.Prefixes)
	if total > 0 && len(toDelete)*100/total > 50 {
		return 0, fmt.Errorf(
			"circuit breaker triggered: cleanup would delete %d of %d prefixes (%d%%), exceeding 50%% safety threshold",
			len(toDelete), total, len(toDelete)*100/total,
		)
	}

	deleteIDs := make(map[int]bool)
	for _, p := range toDelete {
		deleteIDs[p.ID] = true
	}

	var remaining []Prefix
	for _, p := range ps.Prefixes {
		if !deleteIDs[p.ID] {
			remaining = append(remaining, p)
		}
	}

	deleted := len(ps.Prefixes) - len(remaining)
	ps.Prefixes = remaining

	if err := ps.Save(); err != nil {
		return 0, err
	}

	return deleted, nil
}

// HandlePrefixes is the HTTP handler for the /v1/prefixes endpoint
func (ps *PrefixStore) HandlePrefixes(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodGet {
		if r.URL.Query().Has("pending_delete") {
			var pending []Prefix
			for _, p := range ps.Prefixes {
				if p.Status == "pending_delete" {
					pending = append(pending, p)
				}
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(pending)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ps.Prefixes)
		return
	}
	http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Usage: prefixmgr <command> [args]")
		fmt.Println("Commands:")
		fmt.Println("  serve    - Start HTTP API server on :8080")
		fmt.Println("  cleanup  - Run periodic cleanup of pending deletion prefixes")
		fmt.Println("  list [q] - List prefixes, optionally filtered by query string")
		os.Exit(1)
	}

	store, err := NewPrefixStore("/app/data/prefixes.json")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error loading prefix store: %v\n", err)
		os.Exit(1)
	}

	switch os.Args[1] {
	case "serve":
		http.HandleFunc("/v1/prefixes", store.HandlePrefixes)
		fmt.Println("Starting prefix manager on :8080")
		http.ListenAndServe(":8080", nil)

	case "cleanup":
		deleted, err := store.CleanupPrefixes("pending_delete")
		if err != nil {
			fmt.Fprintf(os.Stderr, "Cleanup error: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Cleaned up %d prefixes\n", deleted)

	case "list":
		queryString := ""
		if len(os.Args) > 2 {
			queryString = os.Args[2]
		}
		prefixes := store.FetchPrefixes(queryString)
		data, _ := json.MarshalIndent(prefixes, "", "  ")
		fmt.Println(string(data))

	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", os.Args[1])
		os.Exit(1)
	}
}
