package lib.k8s

# Parse Kubernetes CPU quantity string to millicores.
# Examples: "100m" -> 100, "500m" -> 500, "1" -> 1000, "2" -> 2000
parse_cpu(quantity) = millicores {
    endswith(quantity, "m")
    millicores = to_number(trim_suffix(quantity, "m"))
}

parse_cpu(quantity) = millicores {
    not endswith(quantity, "m")
    millicores = to_number(quantity)
}

# Parse Kubernetes memory quantity string to bytes.
# Examples: "1Gi" -> 1073741824, "512Mi" -> 536870912, "1024Ki" -> 1048576
parse_memory(quantity) = bytes {
    endswith(quantity, "Gi")
    bytes = to_number(trim_suffix(quantity, "Gi")) * 1000 * 1000 * 1000
}

parse_memory(quantity) = bytes {
    endswith(quantity, "Mi")
    bytes = to_number(trim_suffix(quantity, "Mi")) * 1024 * 1024
}

parse_memory(quantity) = bytes {
    endswith(quantity, "Ki")
    bytes = to_number(trim_suffix(quantity, "Ki")) * 1024
}
