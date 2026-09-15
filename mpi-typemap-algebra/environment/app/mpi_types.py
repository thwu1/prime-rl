"""
MPI Derived Datatype Layout Analyzer

Implements the MPI typemap algebra for computing memory layouts
of MPI derived datatypes per the MPI standard specification.

A typemap is a sequence of (basic_type, displacement) pairs that
describes how data elements are laid out in memory. From the typemap,
we derive bounds (lb, ub), extent, true bounds, and data size.
"""

import json


# Basic MPI type definitions (LP64 data model)
BASIC_TYPES = {
    "MPI_CHAR":   {"size": 1, "alignment": 1},
    "MPI_SHORT":  {"size": 2, "alignment": 2},
    "MPI_INT":    {"size": 4, "alignment": 4},
    "MPI_FLOAT":  {"size": 4, "alignment": 4},
    "MPI_LONG":   {"size": 8, "alignment": 8},
    "MPI_DOUBLE": {"size": 8, "alignment": 8},
}

# Pseudo-type markers for explicit bounds
PSEUDO_LB = "__MPI_LB__"
PSEUDO_UB = "__MPI_UB__"


class MPIType:
    """Represents an MPI datatype with its typemap and computed properties."""

    def __init__(self, typemap, name="unnamed"):
        self.typemap = typemap
        self.name = name
        self._compute_properties()

    def _compute_properties(self):
        data_entries = [(t, d) for t, d in self.typemap if t not in (PSEUDO_LB, PSEUDO_UB)]
        lb_entries = [d for t, d in self.typemap if t == PSEUDO_LB]
        ub_entries = [d for t, d in self.typemap if t == PSEUDO_UB]

        if not data_entries:
            self.lb = self.ub = self.extent = 0
            self.true_lb = self.true_ub = self.true_extent = 0
            self.size = 0
            return

        self.true_lb = min(d for _, d in data_entries)
        self.true_ub = max(d + BASIC_TYPES[t]["size"] for t, d in data_entries)
        self.true_extent = self.true_ub - self.true_lb
        self.size = sum(BASIC_TYPES[t]["size"] for t, d in data_entries)

        if lb_entries:
            self.lb = min(lb_entries)
        else:
            self.lb = min(d for _, d in data_entries)

        if ub_entries:
            self.ub = max(ub_entries)
        else:
            raw_ub = max(d + BASIC_TYPES[t]["size"] for t, d in data_entries)
            max_align = max(BASIC_TYPES[t]["alignment"] for t, d in data_entries)
            raw_span = raw_ub - self.lb
            aligned_span = (raw_span // max_align) * max_align
            self.ub = self.lb + aligned_span

        self.extent = self.ub - self.lb

    def get_data_typemap(self):
        return [(t, d) for t, d in self.typemap if t not in (PSEUDO_LB, PSEUDO_UB)]

    def to_dict(self):
        return {
            "typemap": [(t, d) for t, d in self.get_data_typemap()],
            "lb": self.lb, "ub": self.ub, "extent": self.extent,
            "true_lb": self.true_lb, "true_ub": self.true_ub,
            "true_extent": self.true_extent, "size": self.size,
        }


def type_contiguous(count, oldtype, name="unnamed"):
    new_typemap = []
    for i in range(count):
        for t, d in oldtype.typemap:
            new_typemap.append((t, d + i * oldtype.extent))
    return MPIType(new_typemap, name)


def type_vector(count, blocklength, stride, oldtype, name="unnamed"):
    new_typemap = []
    for i in range(count):
        block_start = i * blocklength * oldtype.extent
        for j in range(blocklength):
            for t, d in oldtype.get_data_typemap():
                new_typemap.append((t, d + block_start + j * oldtype.extent))
    return MPIType(new_typemap, name)


def type_create_struct(blocklengths, displacements, types, name="unnamed"):
    new_typemap = []
    for bl, disp, type_name in zip(blocklengths, displacements, types):
        if type_name in BASIC_TYPES:
            for j in range(bl):
                new_typemap.append((type_name, disp + j * BASIC_TYPES[type_name]["size"]))
        else:
            raise ValueError(f"Struct with derived type members not supported: {type_name}")
    return MPIType(new_typemap, name)


def type_create_resized(oldtype, lb, extent, name="unnamed"):
    new_typemap = list(oldtype.get_data_typemap())
    result = MPIType(new_typemap, name)
    result.lb = lb
    result.ub = lb + extent
    result.extent = extent
    return result


def type_create_subarray(sizes, subsizes, starts, order, oldtype, name="unnamed"):
    ndims = len(sizes)
    if order != "C":
        raise ValueError("Only C (row-major) order is supported")
    entries = []
    def compute_offset(indices):
        offset = 0
        for dim in range(ndims):
            dim_stride = 1
            for k in range(dim + 1, ndims):
                dim_stride *= subsizes[k]
            offset += indices[dim] * dim_stride
        return offset * oldtype.extent
    def recurse(dim, indices):
        if dim == ndims:
            offset = compute_offset(indices)
            for t, d in oldtype.get_data_typemap():
                entries.append((t, d + offset))
        else:
            for i in range(subsizes[dim]):
                indices[dim] = starts[dim] + i
                recurse(dim + 1, indices)
    recurse(0, [0] * ndims)
    entries.sort(key=lambda x: x[1])
    total_extent = 1
    for s in sizes:
        total_extent *= s
    total_extent *= oldtype.extent
    entries.insert(0, (PSEUDO_LB, 0))
    entries.append((PSEUDO_UB, total_extent))
    return MPIType(entries, name)


def type_create_hindexed_block(blocklength, displacements, oldtype, name="unnamed"):
    new_typemap = []
    for disp in displacements:
        byte_disp = disp * oldtype.extent
        for j in range(blocklength):
            for t, d in oldtype.get_data_typemap():
                new_typemap.append((t, d + byte_disp + j * oldtype.extent))
    return MPIType(new_typemap, name)


def load_type_defs(filepath):
    with open(filepath) as f:
        return json.load(f)


def build_types(type_defs):
    built = {}
    for name, info in BASIC_TYPES.items():
        bt = MPIType([(name, 0)], name)
        bt.extent = info["size"]
        bt.size = info["size"]
        bt.lb = 0
        bt.ub = info["size"]
        bt.true_lb = 0
        bt.true_ub = info["size"]
        bt.true_extent = info["size"]
        built[name] = bt

    for typedef in type_defs["types"]:
        name = typedef["name"]
        constructor = typedef["constructor"]
        if constructor == "struct":
            dt = type_create_struct(typedef["blocklengths"], typedef["displacements"], typedef["base_types"], name)
        elif constructor == "vector":
            oldtype = built[typedef["oldtype"]]
            dt = type_vector(typedef["count"], typedef["blocklength"], typedef["stride"], oldtype, name)
        elif constructor == "contiguous":
            oldtype = built[typedef["oldtype"]]
            dt = type_contiguous(typedef["count"], oldtype, name)
        elif constructor == "resized":
            oldtype = built[typedef["oldtype"]]
            dt = type_create_resized(oldtype, typedef["lb"], typedef["extent"], name)
        elif constructor == "subarray":
            oldtype = built[typedef["oldtype"]]
            dt = type_create_subarray(typedef["sizes"], typedef["subsizes"], typedef["starts"], typedef["order"], oldtype, name)
        elif constructor == "hindexed_block":
            oldtype = built[typedef["oldtype"]]
            dt = type_create_hindexed_block(typedef["blocklength"], typedef["displacements"], oldtype, name)
        else:
            raise ValueError(f"Unknown constructor: {constructor}")
        built[name] = dt
    return built


def analyze(input_path, output_path):
    type_defs = load_type_defs(input_path)
    types = build_types(type_defs)
    results = {}
    for typedef in type_defs["types"]:
        name = typedef["name"]
        results[name] = types[name].to_dict()
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    return results


if __name__ == "__main__":
    analyze("/app/type_defs.json", "/app/results.json")
