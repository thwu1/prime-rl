# frozen_string_literal: true
# typed: strict

class Crypto < PackageSpec
  # Cryptographic primitives: hashing, encryption, key management.
  layer 'utility'
  strict_dependencies 'dag'

  import Config
end
