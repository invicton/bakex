# AGENTS.md — conventions for AI coding agents

## Build / test / lint

```bash
pip install -e ".[dev,all-providers]"
pytest tests/
ruff check .
```

## Conventions

- Keep all package source code in `bakex/`.
- Provider plugins are located in `plugins/providers/`.
- Ensure new blueprints follow the schema defined in `profiles/templates/`.
- Do not use `# ` (hash followed by space) comment headers inside `llms.txt` quickstart code blocks, as it breaks the Invigil H1 count parser.
- Ensure exit codes for any new CLI commands are documented in `docs/api.md`.
