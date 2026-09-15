#!/usr/bin/env python3

"""
Solver for the hybrid C/Python PagedAttention block manager task.

Fixes:
  1. Makefile: produce .so (not .a), add -fPIC and -shared
  2. blockpool.c: free per-block token_ids in blockpool_destroy
  3. block_manager.py ctypes: blockpool_create restype → c_void_p
  4. block_manager.py: _num_blocks_needed ceil-division
  5. block_manager.py: fork_sequence add child to group_seqs
  6. block_manager.py: swap_in free CPU blocks
  7. block_manager.py: free() clean hash_to_block
  8. block_manager.py: lookup_cache validate ref_count + content
  9. block_manager.py: COW in append_token — use allocator.free()
 10. block_manager.py: implement 3 stubs
"""

import subprocess
import sys


def fix_makefile():
    path = "/app/Makefile"
    with open(path) as f:
        src = f.read()

    src = src.replace("CFLAGS = -Wall -O2",
                      "CFLAGS = -Wall -O2 -fPIC")

    src = src.replace("TARGET = libblockpool.a",
                      "TARGET = libblockpool.so")

    src = src.replace(
        "\t$(CC) $(CFLAGS) -c blockpool.c -o blockpool.o\n"
        "\tar rcs $(TARGET) blockpool.o",
        "\t$(CC) $(CFLAGS) -shared -o $(TARGET) blockpool.c")

    with open(path, "w") as f:
        f.write(src)
    print("[fix] Makefile → shared library with -fPIC")


def fix_blockpool_c():
    path = "/app/blockpool.c"
    with open(path) as f:
        src = f.read()

    # Add loop to free each block's token_ids before freeing the blocks array
    old = (
        "void blockpool_destroy(BlockPool *pool) {\n"
        "    if (!pool) return;\n"
        "    free(pool->blocks);"
    )
    new = (
        "void blockpool_destroy(BlockPool *pool) {\n"
        "    if (!pool) return;\n"
        "    for (int i = 0; i < pool->num_blocks; i++) {\n"
        "        free(pool->blocks[i].token_ids);\n"
        "    }\n"
        "    free(pool->blocks);"
    )
    src = src.replace(old, new)

    with open(path, "w") as f:
        f.write(src)
    print("[fix] blockpool.c → free token_ids in destroy")


def build_library():
    r = subprocess.run(["make", "-C", "/app", "clean"],
                       capture_output=True, text=True)
    r = subprocess.run(["make", "-C", "/app"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"make FAILED:\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    print("[build] libblockpool.so built successfully")


def fix_block_manager():
    path = "/app/block_manager.py"
    with open(path) as f:
        src = f.read()

    # --- Fix 1: ctypes restype for blockpool_create ---
    src = src.replace(
        "self._lib.blockpool_create.restype = ctypes.c_int",
        "self._lib.blockpool_create.restype = ctypes.c_void_p",
    )

    # --- Fix 2: _num_blocks_needed ceil division ---
    src = src.replace(
        "return (num_tokens + self.block_size) // self.block_size",
        "return (num_tokens + self.block_size - 1) // self.block_size",
    )

    # --- Fix 3: fork_sequence add child to group_seqs ---
    src = src.replace(
        "        self.seq_to_group[child_seq_id] = group_id\n"
        "\n"
        "        return True\n"
        "\n"
        "    def free_sequence",
        "        self.seq_to_group[child_seq_id] = group_id\n"
        "        self.group_seqs[group_id].add(child_seq_id)\n"
        "\n"
        "        return True\n"
        "\n"
        "    def free_sequence",
    )

    # --- Fix 4: swap_in free CPU blocks ---
    src = src.replace(
        "                new_table.append(gpu_bid)\n"
        "            self.block_tables[seq_id] = new_table\n"
        "            del self.swapped_block_tables[seq_id]",
        "                new_table.append(gpu_bid)\n"
        "                self.cpu_allocator.free(cpu_bid)\n"
        "            self.block_tables[seq_id] = new_table\n"
        "            del self.swapped_block_tables[seq_id]",
    )

    # --- Fix 5: free() clean hash_to_block ---
    src = src.replace(
        "        if self._lib.blockpool_get_refcount(self._pool, block_id) == 0:\n"
        "            self.blocks[block_id].content_hash = None",
        "        if self._lib.blockpool_get_refcount(self._pool, block_id) == 0:\n"
        "            blk = self.blocks[block_id]\n"
        "            if blk.content_hash is not None and blk.content_hash in self.hash_to_block:\n"
        "                del self.hash_to_block[blk.content_hash]\n"
        "            blk.content_hash = None",
    )

    # --- Fix 6: lookup_cache validate block ---
    src = src.replace(
        "        if block_id is not None:\n"
        "            return block_id\n"
        "        return None",
        "        if block_id is not None:\n"
        "            block = self.blocks[block_id]\n"
        "            if block.ref_count > 0 and block.token_ids == token_ids:\n"
        "                return block_id\n"
        "        return None",
    )

    # --- Fix 7: COW ref_count decrement via allocator.free ---
    src = src.replace(
        "            last_block.ref_count -= 1",
        "            self.gpu_allocator.free(last_block_id)",
    )

    # --- Implement stubs ---

    # get_num_prefix_cache_hits
    src = src.replace(
        '        raise NotImplementedError("get_num_prefix_cache_hits not implemented")',
        "        if not self.enable_prefix_caching:\n"
        "            return 0\n"
        "        hits = 0\n"
        "        for i in range(0, len(token_ids), self.block_size):\n"
        "            chunk = token_ids[i:i + self.block_size]\n"
        "            if len(chunk) < self.block_size:\n"
        "                break\n"
        "            if self.gpu_allocator.lookup_cache(chunk) is not None:\n"
        "                hits += 1\n"
        "            else:\n"
        "                break\n"
        "        return hits",
    )

    # select_victim_group
    src = src.replace(
        '        raise NotImplementedError("select_victim_group not implemented")',
        "        best_group = None\n"
        "        best_arrival = -1\n"
        "        for gid, arrival in self.group_arrival.items():\n"
        "            if gid not in self.group_seqs:\n"
        "                continue\n"
        "            has_active = any(\n"
        "                sid in self.block_tables\n"
        "                for sid in self.group_seqs[gid]\n"
        "            )\n"
        "            if has_active and arrival > best_arrival:\n"
        "                best_arrival = arrival\n"
        "                best_group = gid\n"
        "        return best_group",
    )

    # get_utilization_stats
    src = src.replace(
        '        raise NotImplementedError("get_utilization_stats not implemented")',
        '        gpu_used = self.gpu_allocator.num_blocks - self.gpu_allocator.get_num_free()\n'
        '        cpu_used = self.cpu_allocator.num_blocks - self.cpu_allocator.get_num_free()\n'
        '        shared = sum(\n'
        '            1 for b in self.gpu_allocator.blocks.values()\n'
        '            if b.ref_count > 1\n'
        '        )\n'
        '        return {\n'
        '            "gpu_total_blocks": self.gpu_allocator.num_blocks,\n'
        '            "gpu_used_blocks": gpu_used,\n'
        '            "gpu_free_blocks": self.gpu_allocator.get_num_free(),\n'
        '            "gpu_utilization": gpu_used / self.gpu_allocator.num_blocks if self.gpu_allocator.num_blocks > 0 else 0.0,\n'
        '            "cpu_total_blocks": self.cpu_allocator.num_blocks,\n'
        '            "cpu_used_blocks": cpu_used,\n'
        '            "cpu_free_blocks": self.cpu_allocator.get_num_free(),\n'
        '            "cpu_utilization": cpu_used / self.cpu_allocator.num_blocks if self.cpu_allocator.num_blocks > 0 else 0.0,\n'
        '            "num_active_sequences": len(self.block_tables),\n'
        '            "num_swapped_sequences": len(self.swapped_block_tables),\n'
        '            "num_groups": len(self.group_seqs),\n'
        '            "prefix_cache_size": len(self.gpu_allocator.hash_to_block),\n'
        '            "total_shared_blocks": shared,\n'
        '        }',
    )

    with open(path, "w") as f:
        f.write(src)
    print("[fix] block_manager.py → all bugs fixed + stubs implemented")


def main():
    fix_makefile()
    fix_blockpool_c()
    build_library()
    fix_block_manager()
    print("\nAll fixes applied.")


if __name__ == "__main__":
    main()
