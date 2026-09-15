def rle_encode(data):
    if not data:
        return []
    encoded = []
    count = 1
    for i in range(1, len(data)):
        if data[i] == data[i - 1]:
            count += 1
        else:
            encoded.append((data[i - 1], count))
            count = 0
    encoded.append((data[-1], count))
    return encoded


def rle_decode(encoded):
    result = []
    for value, count in encoded:
        result.extend([value] * count)
    return result
