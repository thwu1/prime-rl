-- bulk_validate.lua: Bulk sorted set validation script
-- Performs deterministic bulk operations and returns validation data.

local key = KEYS[1]
redis.call('DEL', key)

-- Phase 1: Insert 200 members with score = N*7 - 500
for i = 0, 199 do
    local score = i * 7 - 500
    local member = 'member_' .. string.format('%03d', i)
    redis.call('ZADD', key, score, member)
end

-- Phase 2: Remove members where N % 7 == 0
for i = 0, 199, 7 do
    local member = 'member_' .. string.format('%03d', i)
    redis.call('ZREM', key, member)
end

-- Phase 3: Update remaining members where N % 3 == 0: new_score = old_score + 250
for i = 0, 199, 3 do
    local member = 'member_' .. string.format('%03d', i)
    local score = redis.call('ZSCORE', key, member)
    if score ~= false then
        redis.call('ZADD', key, tonumber(score) + 250, member)
    end
end

-- Phase 4: Build and return result string
local card = redis.call('ZCARD', key)
local result = tostring(card)

local probes = {'member_001', 'member_010', 'member_042', 'member_050', 'member_150'}
for _, m in ipairs(probes) do
    local rank = redis.call('ZRANK', key, m)
    local score = redis.call('ZSCORE', key, m)
    if rank ~= false then
        result = result .. ',' .. m .. ':' .. tostring(rank) .. ':' .. score
    else
        result = result .. ',' .. m .. ':nil:nil'
    end
end

return result
