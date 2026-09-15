env "local" {
  url = "postgres://postgres@localhost:5432/appdb?sslmode=disable&search_path=public"
  dev = "postgres://postgres@localhost:5432/appdb_dev?sslmode=disable&search_path=public"
  migration {
    dir = "file:///app/migrations"
  }
}
