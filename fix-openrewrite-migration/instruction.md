A Spring Boot application at `/app/` was migrated from version 2.7 to 3.0 by a departing team member. The migration was done hastily and inconsistently. The application currently fails to compile.

Get the application into a correct, clean Spring Boot 3.0 state where:

- `mvn compile` succeeds
- All dependencies, imports, API usage, and configuration are appropriate and correct for Spring Boot 3.0
- The migration is semantically complete throughout the entire codebase — not just at the compilation level

Not every `javax.*` reference should become `jakarta.*`, and not every existing change is necessarily correct.