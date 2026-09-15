package main


import (
	"fmt"
	"os"
	"slices"

	"github.com/tidwall/btree"
)

func assert(b bool, msg string) {
	if !b {
		panic(msg)
	}
}

func assertEq[C comparable](a C, b C, prefix string) {
	if a != b {
		panic(fmt.Sprintf("%s '%v' != '%v'", prefix, a, b))
	}
}

var DEBUG = slices.Contains(os.Args, "--debug")

func debug(a ...any) {
	if !DEBUG {
		return
	}
	args := append([]any{"[DEBUG]"}, a...)
	fmt.Println(args...)
}

type Value struct {
	txStartId uint64
	txEndId   uint64
	value     string
}

type TransactionState uint8

const (
	InProgressTransaction TransactionState = iota
	AbortedTransaction
	CommittedTransaction
)

type IsolationLevel uint8

const (
	ReadUncommittedIsolation IsolationLevel = iota
	ReadCommittedIsolation
	RepeatableReadIsolation
	SnapshotIsolation
	SerializableIsolation
)

type Transaction struct {
	isolation  IsolationLevel
	id         uint64
	state      TransactionState
	inprogress btree.Set[uint64]
	writeset   btree.Set[string]
	readset    btree.Set[string]
}

type Database struct {
	defaultIsolation  IsolationLevel
	store             map[string][]Value
	transactions      btree.Map[uint64, Transaction]
	nextTransactionId uint64
}

func newDatabase() Database {
	return Database{
		defaultIsolation:  ReadCommittedIsolation,
		store:             map[string][]Value{},
		nextTransactionId: 1,
	}
}

func (d *Database) inprogress() btree.Set[uint64] {
	var ids btree.Set[uint64]
	iter := d.transactions.Iter()
	for ok := iter.First(); ok; ok = iter.Next() {
		if iter.Value().state == InProgressTransaction {
			ids.Insert(iter.Key())
		}
	}
	return ids
}

func (d *Database) newTransaction() *Transaction {
	t := Transaction{}
	t.isolation = d.defaultIsolation
	t.state = InProgressTransaction
	t.id = d.nextTransactionId
	d.nextTransactionId++
	t.inprogress = d.inprogress()
	d.transactions.Set(t.id, t)
	debug("starting transaction", t.id)
	return &t
}

func setsShareItem(s1 btree.Set[string], s2 btree.Set[string]) bool {
	s1Iter := s1.Iter()
	s2Iter := s2.Iter()
	for ok := s1Iter.First(); ok; ok = s1Iter.Next() {
		s1Key := s1Iter.Key()
		found := s2Iter.Seek(s1Key)
		if found {
			return true
		}
	}
	return false
}

func (d *Database) hasConflict(t1 *Transaction, conflictFn func(*Transaction, *Transaction) bool) bool {
	iter := d.transactions.Iter()

	inprogressIter := t1.inprogress.Iter()
	for ok := inprogressIter.First(); ok; ok = inprogressIter.Next() {
		id := inprogressIter.Key()
		found := iter.Seek(id)
		if !found {
			continue
		}
		t2 := iter.Value()
		if t2.state == CommittedTransaction {
			if conflictFn(t1, &t2) {
				return true
			}
		}
	}

	for id := t1.id; id < d.nextTransactionId; id++ {
		found := iter.Seek(id)
		if !found {
			continue
		}
		t2 := iter.Value()
		if t2.state == CommittedTransaction {
			if conflictFn(t1, &t2) {
				return true
			}
		}
	}

	return false
}

func (d *Database) completeTransaction(t *Transaction, state TransactionState) error {
	debug("completing transaction", t.id)

	if state == CommittedTransaction {
		// __STUB_CONFLICT_BEGIN__
		// TODO: Add conflict detection before allowing commit.
		// For Snapshot Isolation, check for write-write conflicts with
		// concurrent committed transactions using hasConflict().
		// For Serializable Isolation, check for read-write conflicts
		// (Write Snapshot Isolation) using hasConflict().
		// On conflict, abort the transaction and return an appropriate error.
		// __STUB_CONFLICT_END__
	}

	t.state = state
	d.transactions.Set(t.id, *t)
	return nil
}

func (d *Database) transactionState(txId uint64) Transaction {
	t, ok := d.transactions.Get(txId)
	assert(ok, "valid transaction")
	return t
}

func (d *Database) assertValidTransaction(t *Transaction) {
	assert(t.id > 0, "valid id")
	assert(d.transactionState(t.id).state == InProgressTransaction, "in progress")
}

func (d *Database) isvisible(t *Transaction, value Value) bool {
	if t.isolation == ReadUncommittedIsolation {
		return value.txEndId == 0
	}

	// __STUB_RC_BEGIN__
	if t.isolation == ReadCommittedIsolation {
		// TODO: Implement Read Committed visibility.
		// A value is visible if it was created by this transaction or
		// a committed transaction. A value is not visible if it was
		// deleted by this transaction or by any committed transaction.
		// Uncommitted or aborted deletes must not hide values.
		return false
	}
	// __STUB_RC_END__

	// __STUB_SNAPSHOT_BEGIN__
	assert(t.isolation == RepeatableReadIsolation ||
		t.isolation == SnapshotIsolation ||
		t.isolation == SerializableIsolation, "invalid isolation level")
	// TODO: Implement snapshot-based visibility for Repeatable Read,
	// Snapshot Isolation, and Serializable isolation levels.
	// These share the same visibility rules (they differ in conflict
	// detection at commit time, not in what values are visible).
	// The snapshot should reflect the database state as of this
	// transaction's start:
	// - Values from transactions started after this one are not visible
	// - Values from transactions in-progress at this one's start are not visible
	// - Only values from committed transactions (or this transaction) are visible
	// - Deletions by transactions that were in-progress at start time
	//   should not affect the snapshot even if those transactions
	//   subsequently committed
	return false
	// __STUB_SNAPSHOT_END__
}

// __STUB_VACUUM_BEGIN__
func (d *Database) vacuum() {
	// TODO: Implement garbage collection for old value versions.
	// Should remove versions that are no longer visible to any
	// active or future transaction:
	// - Versions created by aborted transactions can always be removed
	// - Versions superseded (txEndId set and committed) before all
	//   currently active transactions can be removed
	// - Keys with no remaining versions should be removed from the store
}

// __STUB_VACUUM_END__

type Connection struct {
	tx *Transaction
	db *Database
}

func (c *Connection) execCommand(command string, args []string) (string, error) {
	debug(command, args)

	if command == "begin" {
		assertEq(c.tx, nil, "no running transactions")
		c.tx = c.db.newTransaction()
		c.db.assertValidTransaction(c.tx)
		return fmt.Sprintf("%d", c.tx.id), nil
	}

	if command == "abort" {
		c.db.assertValidTransaction(c.tx)
		err := c.db.completeTransaction(c.tx, AbortedTransaction)
		c.tx = nil
		return "", err
	}

	if command == "commit" {
		c.db.assertValidTransaction(c.tx)
		err := c.db.completeTransaction(c.tx, CommittedTransaction)
		c.tx = nil
		return "", err
	}

	if command == "set" || command == "delete" {
		c.db.assertValidTransaction(c.tx)

		key := args[0]

		found := false
		for i := len(c.db.store[key]) - 1; i >= 0; i-- {
			value := &c.db.store[key][i]
			debug(value, c.tx, c.db.isvisible(c.tx, *value))
			if c.db.isvisible(c.tx, *value) {
				value.txEndId = c.tx.id
				found = true
			}
		}
		if command == "delete" && !found {
			return "", fmt.Errorf("cannot delete key that does not exist")
		}

		c.tx.writeset.Insert(key)

		if command == "set" {
			value := args[1]
			c.db.store[key] = append(c.db.store[key], Value{
				txStartId: c.tx.id,
				txEndId:   0,
				value:     value,
			})
			return value, nil
		}

		return "", nil
	}

	if command == "get" {
		c.db.assertValidTransaction(c.tx)

		key := args[0]

		c.tx.readset.Insert(key)

		for i := len(c.db.store[key]) - 1; i >= 0; i-- {
			value := c.db.store[key][i]
			debug(value, c.tx, c.db.isvisible(c.tx, value))
			if c.db.isvisible(c.tx, value) {
				return value.value, nil
			}
		}

		return "", fmt.Errorf("cannot get key that does not exist")
	}

	return "", fmt.Errorf("unimplemented")
}

func (c *Connection) mustExecCommand(cmd string, args []string) string {
	res, err := c.execCommand(cmd, args)
	assertEq(err, nil, "unexpected error")
	return res
}

func (d *Database) newConnection() *Connection {
	return &Connection{
		db: d,
		tx: nil,
	}
}

func main() {
	fmt.Println("MVCC key-value store ready")
}
