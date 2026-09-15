A PostgreSQL database managed by Atlas at `/app` has entered a broken state after a failed deployment.

The database `appdb` on `localhost:5432` (user: `atlas`, password: `atlas`) has 5 versioned migrations in `/app/migrations/`. The first two applied successfully. The third migration was configured with `-- atlas:txmode none` (required for a concurrent index operation) and failed partway through, leaving partially-applied schema changes in the database. A DBA then manually intervened and made unauthorized schema modifications directly on the live database, introducing schema drift. Two additional migrations remain pending.

Bring the database to a fully consistent state: all 5 migrations successfully applied, the Atlas revision table reflecting no pending or failed migrations, the migration directory integrity valid (`atlas.sum` consistent), all schema drift from manual interventions reversed, and the original seed data (3 customers, 3 products, 4 orders) preserved.

The Atlas configuration is at `/app/atlas.hcl`. Work in the `/app` directory.