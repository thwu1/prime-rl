#!/bin/bash
# Create sysfs_slab directory structure mimicking /sys/kernel/slab/

BASE="/app/sysfs_slab"

create_cache() {
    local name="$1"
    local objsize="$2"
    local slabsize="$3"
    local align="$4"
    local ctor="$5"
    local destroy_by_rcu="$6"
    local poison="$7"
    local store_user="$8"
    local trace="$9"

    mkdir -p "$BASE/$name"
    echo "$objsize" > "$BASE/$name/object_size"
    echo "$slabsize" > "$BASE/$name/slab_size"
    echo "$align" > "$BASE/$name/align"
    echo "$ctor" > "$BASE/$name/ctor"
    echo "$destroy_by_rcu" > "$BASE/$name/destroy_by_rcu"
    echo "$poison" > "$BASE/$name/poison"
    echo "$store_user" > "$BASE/$name/store_user"
    echo "$trace" > "$BASE/$name/trace"
}

# Generic kmalloc caches
create_cache "kmalloc-32"   32   4096 8 "" 0 0 0 0
create_cache "kmalloc-64"   64   4096 8 "" 0 0 0 0
create_cache "kmalloc-96"   96   4096 8 "" 0 0 0 0
create_cache "kmalloc-128"  128  4096 8 "" 0 0 0 0
create_cache "kmalloc-192"  192  4096 8 "" 0 0 0 0
create_cache "kmalloc-256"  256  4096 8 "" 0 0 0 0
create_cache "kmalloc-512"  512  4096 8 "" 0 0 0 0
create_cache "kmalloc-1024" 1024 8192 8 "" 0 0 0 0

# Named caches
create_cache "drill_cache"    192  4096 8 ""             0 0 0 0
create_cache "cred_jar"       192  4096 8 ""             1 0 0 0
create_cache "sighand_cache"  1024 8192 8 "sighand_ctor" 0 0 0 0
