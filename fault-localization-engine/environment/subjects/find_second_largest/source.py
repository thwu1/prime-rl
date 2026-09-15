def find_second_largest(nums):
    if len(nums) < 2:
        return None
    first = second = float('-inf')
    for n in nums:
        if n > first:
            second = first
            first = n
        elif n > second:
            second = n
    if second == float('-inf'):
        return None
    return second
