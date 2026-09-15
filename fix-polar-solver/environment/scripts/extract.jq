# Extract flat coefficient configuration from nested JSON config file
# Input: nested config with metadata and parameters
# Output: {name, coefficients: [[a,b,c], ...]}
{
  name: .metadata.name,
  coefficients: [.parameters.coefficients[] | [.a, .b, .c]]
}
