#!/bin/bash

cp /solution/allocator_impl.py /app/allocator.py

cd /app
python3 -c "
from allocator import FrameAllocator
from config import TOTAL_PAGES, NR_ZONES

alloc = FrameAllocator()
total = sum(alloc.get_zone_stats(z)['free_pages'] for z in range(NR_ZONES))
assert total == TOTAL_PAGES, f'Init failed: {total} != {TOTAL_PAGES}'
pfn = alloc.alloc_pages(0, 1, 1)
assert pfn >= 0, 'Alloc failed'
alloc.free_pages(pfn, 0)
print('Solution verified.')
"
