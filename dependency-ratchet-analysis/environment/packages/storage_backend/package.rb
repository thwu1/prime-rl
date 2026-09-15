# frozen_string_literal: true
# typed: strict

class StorageBackend < PackageSpec
  # Object storage abstraction (S3, GCS, local filesystem).
  layer 'power'
  strict_dependencies 'layered_dag'

  import HttpClient
  import Logging
  import Config
  import Database
end
