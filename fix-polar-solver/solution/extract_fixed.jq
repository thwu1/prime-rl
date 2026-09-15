# Extract flat coefficient configuration from nested JSON config file
# Input: nested config with metadata and parameters.iterations
# Output: {name, coefficients: [[a,b,c], ...]}
{
  name: .metadata.name,
  coefficients: [.parameters.iterations | sort_by(.step)[] | [.coefficients.a, .coefficients.b, .coefficients.c]]
}
