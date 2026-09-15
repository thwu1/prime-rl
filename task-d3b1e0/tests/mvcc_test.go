package main


import "testing"

func TestReadUncommitted(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = ReadUncommittedIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)

	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)

	c1.mustExecCommand("set", []string{"x", "hey"})

	res := c1.mustExecCommand("get", []string{"x"})
	if res != "hey" {
		t.Fatalf("c1 should see own write 'hey', got '%s'", res)
	}

	res = c2.mustExecCommand("get", []string{"x"})
	if res != "hey" {
		t.Fatalf("c2 should see uncommitted 'hey' (read uncommitted), got '%s'", res)
	}

	c1.mustExecCommand("delete", []string{"x"})

	_, err := c1.execCommand("get", []string{"x"})
	if err == nil {
		t.Fatal("c1 should not see deleted x")
	}

	_, err = c2.execCommand("get", []string{"x"})
	if err == nil {
		t.Fatal("c2 should not see deleted x (read uncommitted)")
	}
}

func TestReadCommittedBasic(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = ReadCommittedIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)

	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)

	c1.mustExecCommand("set", []string{"x", "hey"})

	res := c1.mustExecCommand("get", []string{"x"})
	if res != "hey" {
		t.Fatalf("c1 should see own write 'hey', got '%s'", res)
	}

	_, err := c2.execCommand("get", []string{"x"})
	if err == nil {
		t.Fatal("c2 should not see uncommitted value from c1")
	}

	c1.mustExecCommand("commit", nil)

	res = c2.mustExecCommand("get", []string{"x"})
	if res != "hey" {
		t.Fatalf("c2 should see committed value 'hey', got '%s'", res)
	}
}

func TestReadCommittedAbortedDelete(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = ReadCommittedIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)
	c1.mustExecCommand("set", []string{"x", "hello"})
	c1.mustExecCommand("commit", nil)

	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)

	c3 := database.newConnection()
	c3.mustExecCommand("begin", nil)
	c3.mustExecCommand("delete", []string{"x"})

	// c2 should still see x because c3 has not committed the delete
	res, err := c2.execCommand("get", []string{"x"})
	if err != nil {
		t.Fatalf("c2 should see x despite uncommitted delete, got error: %v", err)
	}
	if res != "hello" {
		t.Fatalf("c2 should see 'hello', got '%s'", res)
	}

	c3.mustExecCommand("abort", nil)

	// c2 should still see x after c3 aborted
	res, err = c2.execCommand("get", []string{"x"})
	if err != nil {
		t.Fatalf("c2 should see x after aborted delete, got error: %v", err)
	}
	if res != "hello" {
		t.Fatalf("c2 should see 'hello' after abort, got '%s'", res)
	}
}

func TestReadCommittedInProgressDelete(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = ReadCommittedIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)
	c1.mustExecCommand("set", []string{"y", "world"})
	c1.mustExecCommand("commit", nil)

	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)
	c2.mustExecCommand("delete", []string{"y"})
	// c2 does NOT commit or abort yet

	c3 := database.newConnection()
	c3.mustExecCommand("begin", nil)

	// c3 should still see y because c2 is in-progress
	res, err := c3.execCommand("get", []string{"y"})
	if err != nil {
		t.Fatalf("c3 should see y while delete is in-progress, got error: %v", err)
	}
	if res != "world" {
		t.Fatalf("c3 should see 'world', got '%s'", res)
	}

	// Now c2 commits the delete
	c2.mustExecCommand("commit", nil)

	// c3 should now NOT see y
	_, err = c3.execCommand("get", []string{"y"})
	if err == nil {
		t.Fatal("c3 should not see y after delete was committed")
	}
}

func TestRepeatableReadBasic(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = RepeatableReadIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)

	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)

	c1.mustExecCommand("set", []string{"x", "hey"})
	res := c1.mustExecCommand("get", []string{"x"})
	if res != "hey" {
		t.Fatalf("c1 should see 'hey', got '%s'", res)
	}

	_, err := c2.execCommand("get", []string{"x"})
	if err == nil {
		t.Fatal("c2 should not see uncommitted value")
	}

	c1.mustExecCommand("commit", nil)

	// Even after commit, not visible in existing RR transaction
	_, err = c2.execCommand("get", []string{"x"})
	if err == nil {
		t.Fatal("c2 should not see value committed after c2 started (repeatable read)")
	}

	// But visible in a new transaction
	c3 := database.newConnection()
	c3.mustExecCommand("begin", nil)
	res = c3.mustExecCommand("get", []string{"x"})
	if res != "hey" {
		t.Fatalf("c3 should see 'hey', got '%s'", res)
	}
}

func TestRepeatableReadConcurrentDelete(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = RepeatableReadIsolation

	// Set up initial committed value
	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)
	c1.mustExecCommand("set", []string{"x", "hello"})
	c1.mustExecCommand("commit", nil)

	// c2 begins — will be in c3's inprogress set
	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)

	// c3 begins — c2 is in c3's inprogress set
	c3 := database.newConnection()
	c3.mustExecCommand("begin", nil)

	// c2 deletes x and commits
	c2.mustExecCommand("delete", []string{"x"})
	c2.mustExecCommand("commit", nil)

	// c3 should still see x because c2 was in-progress when c3 started
	res, err := c3.execCommand("get", []string{"x"})
	if err != nil {
		t.Fatalf("c3 should see x (c2 was in-progress at c3's start), got error: %v", err)
	}
	if res != "hello" {
		t.Fatalf("c3 should see 'hello', got '%s'", res)
	}
}

func TestRepeatableReadConcurrentUpdate(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = RepeatableReadIsolation

	// Set up initial committed value
	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)
	c1.mustExecCommand("set", []string{"x", "v1"})
	c1.mustExecCommand("commit", nil)

	// c2 begins — will be in c3's inprogress set
	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)

	// c3 begins — c2 is in c3's inprogress set
	c3 := database.newConnection()
	c3.mustExecCommand("begin", nil)

	// c2 updates x and commits
	c2.mustExecCommand("set", []string{"x", "v2"})
	c2.mustExecCommand("commit", nil)

	// c3 should still see v1 because c2 was in-progress when c3 started
	res := c3.mustExecCommand("get", []string{"x"})
	if res != "v1" {
		t.Fatalf("c3 should see 'v1' (snapshot), got '%s'", res)
	}

	// New transaction should see v2
	c4 := database.newConnection()
	c4.mustExecCommand("begin", nil)
	res = c4.mustExecCommand("get", []string{"x"})
	if res != "v2" {
		t.Fatalf("c4 should see 'v2', got '%s'", res)
	}
}

func TestSnapshotIsolationWriteWriteConflict(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = SnapshotIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)

	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)

	c3 := database.newConnection()
	c3.mustExecCommand("begin", nil)

	c1.mustExecCommand("set", []string{"x", "hey"})
	c1.mustExecCommand("commit", nil)

	c2.mustExecCommand("set", []string{"x", "conflict"})
	_, err := c2.execCommand("commit", nil)
	if err == nil {
		t.Fatal("c2 commit should fail with write-write conflict")
	}
	if err.Error() != "write-write conflict" {
		t.Fatalf("expected 'write-write conflict', got '%s'", err.Error())
	}

	// Unrelated keys cause no conflict
	c3.mustExecCommand("set", []string{"y", "no conflict"})
	c3.mustExecCommand("commit", nil)
}

func TestSerializableReadWriteConflict(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = SerializableIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)

	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)

	c3 := database.newConnection()
	c3.mustExecCommand("begin", nil)

	c1.mustExecCommand("set", []string{"x", "hey"})
	c1.mustExecCommand("commit", nil)

	// c2 reads x — cannot see it because c1 was in-progress at c2's start
	_, err := c2.execCommand("get", []string{"x"})
	if err == nil || err.Error() != "cannot get key that does not exist" {
		t.Fatalf("unexpected result for c2 get x: err=%v", err)
	}

	// c2 should fail to commit because of read-write conflict
	_, err = c2.execCommand("commit", nil)
	if err == nil {
		t.Fatal("c2 commit should fail with read-write conflict")
	}
	if err.Error() != "read-write conflict" {
		t.Fatalf("expected 'read-write conflict', got '%s'", err.Error())
	}

	// Unrelated keys cause no conflict
	c3.mustExecCommand("set", []string{"y", "no conflict"})
	c3.mustExecCommand("commit", nil)
}

func TestSerializableWriteReadConflict(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = SerializableIsolation

	// Set up initial value
	c0 := database.newConnection()
	c0.mustExecCommand("begin", nil)
	c0.mustExecCommand("set", []string{"x", "initial"})
	c0.mustExecCommand("commit", nil)

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)

	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)

	// c1 reads x
	res := c1.mustExecCommand("get", []string{"x"})
	if res != "initial" {
		t.Fatalf("c1 should see 'initial', got '%s'", res)
	}

	// c2 writes x and commits
	c2.mustExecCommand("set", []string{"x", "modified"})
	c2.mustExecCommand("commit", nil)

	// c1 should fail to commit because c2 wrote a key that c1 read
	_, err := c1.execCommand("commit", nil)
	if err == nil {
		t.Fatal("c1 commit should fail with read-write conflict")
	}
	if err.Error() != "read-write conflict" {
		t.Fatalf("expected 'read-write conflict', got '%s'", err.Error())
	}
}

func TestVacuumBasic(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = ReadCommittedIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)
	c1.mustExecCommand("set", []string{"x", "v1"})
	c1.mustExecCommand("commit", nil)

	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)
	c2.mustExecCommand("set", []string{"x", "v2"})
	c2.mustExecCommand("commit", nil)

	if len(database.store["x"]) < 2 {
		t.Fatalf("expected at least 2 versions before vacuum, got %d", len(database.store["x"]))
	}

	database.vacuum()

	if len(database.store["x"]) != 1 {
		t.Fatalf("expected 1 version after vacuum, got %d", len(database.store["x"]))
	}

	// The remaining version should be the latest
	c3 := database.newConnection()
	c3.mustExecCommand("begin", nil)
	res := c3.mustExecCommand("get", []string{"x"})
	if res != "v2" {
		t.Fatalf("expected 'v2' after vacuum, got '%s'", res)
	}
}

func TestVacuumPreservesActiveTransactionVersions(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = RepeatableReadIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)
	c1.mustExecCommand("set", []string{"x", "v1"})
	c1.mustExecCommand("commit", nil)

	// Start a long-running transaction that needs the old version
	cLong := database.newConnection()
	cLong.mustExecCommand("begin", nil)

	res := cLong.mustExecCommand("get", []string{"x"})
	if res != "v1" {
		t.Fatalf("long tx should see 'v1', got '%s'", res)
	}

	// Update in a new transaction
	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)
	c2.mustExecCommand("set", []string{"x", "v2"})
	c2.mustExecCommand("commit", nil)

	database.vacuum()

	// Both versions must be preserved — cLong needs v1
	if len(database.store["x"]) < 2 {
		t.Fatalf("expected 2 versions preserved for active tx, got %d", len(database.store["x"]))
	}

	// Long-running transaction should still see v1
	res = cLong.mustExecCommand("get", []string{"x"})
	if res != "v1" {
		t.Fatalf("long tx should still see 'v1' after vacuum, got '%s'", res)
	}
}

func TestVacuumCleansAbortedVersions(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = ReadCommittedIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)
	c1.mustExecCommand("set", []string{"x", "v1"})
	c1.mustExecCommand("abort", nil)

	if len(database.store["x"]) != 1 {
		t.Fatalf("expected 1 version before vacuum, got %d", len(database.store["x"]))
	}

	database.vacuum()

	if len(database.store["x"]) != 0 {
		t.Fatalf("expected 0 versions after vacuum for aborted tx, got %d", len(database.store["x"]))
	}
}

func TestVacuumDeletedKey(t *testing.T) {
	database := newDatabase()
	database.defaultIsolation = ReadCommittedIsolation

	c1 := database.newConnection()
	c1.mustExecCommand("begin", nil)
	c1.mustExecCommand("set", []string{"x", "v1"})
	c1.mustExecCommand("commit", nil)

	c2 := database.newConnection()
	c2.mustExecCommand("begin", nil)
	c2.mustExecCommand("delete", []string{"x"})
	c2.mustExecCommand("commit", nil)

	database.vacuum()

	if versions, exists := database.store["x"]; exists && len(versions) > 0 {
		t.Fatalf("expected key to be removed after vacuum, but has %d versions", len(versions))
	}
}
