
#=
Quantum state-vector simulator in Julia.

Applies unitary gates to a state vector by iterating over all configurations
of non-target qubits, extracting a sub-vector from the target qubit subspace,
multiplying by the gate matrix, and writing back.
=#

using JSON
using LinearAlgebra


function apply_gate!(state::Vector{ComplexF64}, matrix::Matrix{ComplexF64},
                     target_qubits::Vector{Int})
    n_qubits = trailing_zeros(length(state))
    k = length(target_qubits)
    other_qubits = sort([q for q in 0:n_qubits-1 if !(q in target_qubits)])
    n_other = length(other_qubits)

    # Precompute complement offsets for each target qubit combination
    dim = 1 << k
    offsets = Vector{Int}(undef, dim)
    for j in 0:dim-1
        off = 0
        for b in 0:k-1
            if (j >> b) & 1 == 1
                off |= (1 << target_qubits[b+1])
            end
        end
        offsets[j+1] = off
    end

    sub_vec = Vector{ComplexF64}(undef, dim)
    result_vec = Vector{ComplexF64}(undef, dim)

    for sub_idx in 0:(1 << n_other)-1
        base = 0
        for (bp, qubit) in enumerate(other_qubits)
            if (sub_idx >> (bp - 1)) & 1 == 1
                base |= (1 << qubit)
            end
        end

        # Gather sub-vector
        @inbounds for j in 1:dim
            sub_vec[j] = state[(base | offsets[j]) + 1]
        end

        # Matrix-vector multiply in-place
        mul!(result_vec, matrix, sub_vec)

        # Scatter result back
        @inbounds for j in 1:dim
            state[(base | offsets[j]) + 1] = result_vec[j]
        end
    end

    return state
end


function apply_controlled_gate!(state::Vector{ComplexF64}, matrix::Matrix{ComplexF64},
                                target_qubits::Vector{Int}, control_qubits::Vector{Int},
                                control_values::Vector{Int})
    n_qubits = trailing_zeros(length(state))
    k = length(target_qubits)

    all_fixed = sort(unique(vcat(target_qubits, control_qubits)))
    other_qubits = sort([q for q in 0:n_qubits-1 if !(q in all_fixed)])
    n_other = length(other_qubits)

    # Control offset: pre-set bits for control qubits with value 1
    ctrl_offset = 0
    for (q, v) in zip(control_qubits, control_values)
        if v == 1
            ctrl_offset |= (1 << q)
        end
    end

    # Complement offsets for target qubits
    dim = 1 << k
    offsets = Vector{Int}(undef, dim)
    for j in 0:dim-1
        off = 0
        for b in 0:k-1
            if (j >> b) & 1 == 1
                off |= (1 << target_qubits[b+1])
            end
        end
        offsets[j+1] = off
    end

    sub_vec = Vector{ComplexF64}(undef, dim)
    result_vec = Vector{ComplexF64}(undef, dim)

    for sub_idx in 0:(1 << n_other)-1
        base = ctrl_offset
        for (bp, qubit) in enumerate(other_qubits)
            if (sub_idx >> (bp - 1)) & 1 == 1
                base |= (1 << qubit)
            end
        end

        @inbounds for j in 1:dim
            sub_vec[j] = state[(base | offsets[j]) + 1]
        end

        mul!(result_vec, matrix, sub_vec)

        @inbounds for j in 1:dim
            state[(base | offsets[j]) + 1] = result_vec[j]
        end
    end

    return state
end


function get_gate_matrix(gate_def)
    name = gate_def["gate"]

    if name == "H"
        return ComplexF64[1 1; 1 -1] / sqrt(2)
    elseif name == "X"
        return ComplexF64[0 1; 1 0]
    elseif name == "Y"
        return ComplexF64[0 -im; im 0]
    elseif name == "Z"
        return ComplexF64[1 0; 0 -1]
    elseif name == "S"
        return ComplexF64[1 0; 0 im]
    elseif name == "T"
        return ComplexF64[1 0; 0 exp(im * pi / 4)]
    elseif name == "RX"
        theta = Float64(gate_def["params"]["theta"])
        c, s = cos(theta / 2), sin(theta / 2)
        return ComplexF64[c -im*s; -im*s c]
    elseif name == "RY"
        theta = Float64(gate_def["params"]["theta"])
        c, s = cos(theta / 2), sin(theta / 2)
        return ComplexF64[c -s; s c]
    elseif name == "RZ"
        theta = Float64(gate_def["params"]["theta"])
        return ComplexF64[exp(-im*theta/2) 0; 0 exp(im*theta/2)]
    elseif name == "SWAP"
        return ComplexF64[1 0 0 0; 0 0 1 0; 0 1 0 0; 0 0 0 1]
    elseif name == "CUSTOM"
        rows_r = gate_def["matrix_real"]
        rows_i = gate_def["matrix_imag"]
        n = length(rows_r)
        mat = Matrix{ComplexF64}(undef, n, n)
        for i in 1:n
            for j in 1:n
                mat[i, j] = complex(Float64(rows_r[i][j]), Float64(rows_i[i][j]))
            end
        end
        return mat
    else
        error("Unknown gate: $name")
    end
end


function main()
    input_path = ARGS[1]
    output_path = ARGS[2]

    circuit = JSON.parsefile(input_path)
    n_qubits = Int(circuit["n_qubits"])

    state = zeros(ComplexF64, 1 << n_qubits)
    state[1] = 1.0  # |0...0> in Julia 1-indexed

    for gate_def in circuit["gates"]
        matrix = get_gate_matrix(gate_def)
        targets = Int.(gate_def["targets"])

        if haskey(gate_def, "controls") && !isempty(gate_def["controls"])
            ctrl_qubits = Int.([c["qubit"] for c in gate_def["controls"]])
            ctrl_values = Int.([c["value"] for c in gate_def["controls"]])
            apply_controlled_gate!(state, matrix, targets, ctrl_qubits, ctrl_values)
        else
            apply_gate!(state, matrix, targets)
        end
    end

    # Write output
    state_pairs = [[real(x), imag(x)] for x in state]
    output = Dict("n_qubits" => n_qubits, "state" => state_pairs)

    open(output_path, "w") do f
        JSON.print(f, output)
    end

    norm_sq = sum(abs2, state)
    println(stderr, "Simulation complete: $n_qubits qubits, norm^2 = $norm_sq")
end

main()
