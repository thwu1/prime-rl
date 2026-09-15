-- bulk_validate.lua: Bulk sorted set validation script
-- Execute: redis-cli EVAL "$(cat /app/bulk_validate.lua)" 1 tbench:test
--
-- This script performs deterministic bulk operations on a Redis sorted set
-- and returns a validation string for cross-checking against the Python
-- SortedSet implementation.
--
-- Operations:
--   Phase 1: Insert member_000..member_199 with score = N*7 - 500
--   Phase 2: Remove members where N % 7 == 0
--   Phase 3: For remaining members where N % 3 == 0, add 250 to their score
--   Phase 4: Return result string
--
-- Output format:
--   "card,member_001:rank:score,member_010:rank:score,member_042:rank:score,member_050:rank:score,member_150:rank:score"
--   Use "nil:nil" for rank:score if the member was removed.

local key = KEYS[1]
redis.call('DEL', key)

-- Phase 1: Insert 200 members with score = N*7 - 500
-- TODO: implement insertion loop

-- Phase 2: Remove members where N % 7 == 0
-- TODO: implement removal loop

-- Phase 3: Update remaining members where N % 3 == 0: new_score = old_score + 250
-- TODO: implement update loop

-- Phase 4: Build and return result string
-- Probe members: member_001, member_010, member_042, member_050, member_150
-- For each probe, get ZRANK and ZSCORE. If member was removed, use nil:nil.
local probes = {'member_001', 'member_010', 'member_042', 'member_050', 'member_150'}
-- TODO: collect card, iterate probes, build comma-separated result string, return it
