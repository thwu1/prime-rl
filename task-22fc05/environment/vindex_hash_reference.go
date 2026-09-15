// Reference implementation: Vitess Hash Vindex
// Source: vitess.io/vitess/go/vt/vtgate/vindexes/hash.go
//
// This file is provided as a reference for the hashing algorithm.
// It is not compilable outside the Vitess module — use it to
// understand the algorithm and translate it to Python.

package vindexes

import (
	"crypto/cipher"
	"crypto/des"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"strconv"
)

// Hash defines vindex that hashes an int64 to a KeyspaceId
// by using null-key DES hash. It's Unique, Reversible and
// Functional.
type Hash struct {
	name string
}

var blockDES cipher.Block

func init() {
	var err error
	// DES cipher with an 8-byte null (all-zeros) key
	blockDES, err = des.NewCipher(make([]byte, 8))
	if err != nil {
		panic(err)
	}
}

// vhash computes the keyspace ID for a uint64 shard key.
// Steps:
//  1. Encode shardKey as 8 bytes in big-endian order
//  2. Encrypt those 8 bytes using DES with null key (single-block ECB)
//  3. Return the 8-byte ciphertext as the keyspace ID
func vhash(shardKey uint64) []byte {
	var keybytes, hashed [8]byte
	binary.BigEndian.PutUint64(keybytes[:], shardKey)
	blockDES.Encrypt(hashed[:], keybytes[:])
	return hashed[:]
}

// vunhash reverses the hash by decrypting the keyspace ID.
func vunhash(k []byte) (uint64, error) {
	if len(k) != 8 {
		return 0, fmt.Errorf("invalid keyspace id: %v", hex.EncodeToString(k))
	}
	var unhashed [8]byte
	blockDES.Decrypt(unhashed[:], k)
	return binary.BigEndian.Uint64(unhashed[:]), nil
}

// Hash method on the Hash vindex. For signed integers, the value
// is cast from int64 to uint64 preserving the bit pattern
// (not the mathematical value):
//
//	if id.IsSigned() {
//	    str := id.ToString()
//	    var ival int64
//	    ival, err = strconv.ParseInt(str, 10, 64)
//	    num = uint64(ival)  // bit-pattern-preserving cast
//	} else {
//	    num, err = id.ToCastUint64()
//	}
//	return vhash(num)
func (vind *Hash) HashValue(idStr string, signed bool) ([]byte, error) {
	var num uint64
	if signed {
		ival, err := strconv.ParseInt(idStr, 10, 64)
		if err != nil {
			return nil, err
		}
		num = uint64(ival)
	} else {
		uval, err := strconv.ParseUint(idStr, 10, 64)
		if err != nil {
			return nil, err
		}
		num = uval
	}
	return vhash(num), nil
}

func (vind *Hash) Cost() int    { return 1 }
func (vind *Hash) IsUnique() bool { return true }
