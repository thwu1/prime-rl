package lib.k8s

test_parse_cpu_millicores {
    parse_cpu("100m") == 100
}

test_parse_cpu_millicores_500 {
    parse_cpu("500m") == 500
}

test_parse_cpu_whole_cores {
    parse_cpu("1") == 1000
}

test_parse_cpu_whole_cores_multi {
    parse_cpu("2") == 2000
}

test_parse_cpu_whole_cores_large {
    parse_cpu("16") == 16000
}

test_parse_memory_gi {
    parse_memory("1Gi") == 1073741824
}

test_parse_memory_gi_multi {
    parse_memory("2Gi") == 2147483648
}

test_parse_memory_gi_large {
    parse_memory("64Gi") == 68719476736
}

test_parse_memory_mi {
    parse_memory("512Mi") == 536870912
}

test_parse_memory_mi_small {
    parse_memory("256Mi") == 268435456
}

test_parse_memory_ki {
    parse_memory("1024Ki") == 1048576
}
