# Tests

- **Unit tests** are fully offline (models/LLM patched, no services). They run anywhere.
- **Integration tests** use real services (Postgres, Redis, Qdrant) per the
  `run-and-test` skill. They connect to a **dedicated `eudi_test` database**, never the
  dev/live `eudi` database — so a crashed or interrupted run can never leak fixture rows
  into the dashboard/search. Each integration test seeds and tears down its own rows.
- **Eval gates** (grounding, recall) hit the full running stack and are opt-in via
  `RUN_GROUNDING_EVAL=1` / `RUN_RECALL_EVAL=1`.

Integration tests **skip** (not fail) when `eudi_test` is absent or unmigrated.

## One-time setup of the test database

```bash
docker compose exec -T postgres psql -U eudi -d eudi -c "CREATE DATABASE eudi_test;"
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://eudi:eudi@postgres:5432/eudi_test \
  api alembic upgrade head
```

Re-run the `alembic upgrade head` line after adding a migration. Override the URL with
`TEST_DATABASE_URL` if needed (default: `postgresql+asyncpg://eudi:eudi@localhost:5432/eudi_test`).
