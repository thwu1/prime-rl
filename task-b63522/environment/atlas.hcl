env "local" {
  url = "postgres://atlas:atlas@localhost:5432/appdb?search_path=public&sslmode=disable"
  dev = "postgres://atlas:atlas@localhost:5432/devdb?search_path=public&sslmode=disable"
  migration {
    dir = "file://migrations"
  }
}
