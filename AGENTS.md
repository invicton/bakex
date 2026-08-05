# AGENTS.md — conventions for AI coding agents

## Build / test / lint

```bash
pip install -e ".[dev,all-providers]"
pytest tests/
ruff check .
```

## Conventions

- Keep all package source code in `bakex/`.
- The project was called Stratum through v0.5.2. `import stratum`, `STRATUM_*` env vars,
  `stratum_version:` in a blueprint, and the PyPI name `stratumoss` are all stale — use
  `bakex`, `BAKEX_*`, `bakex_version:` and `pip install bakex`. Do not reintroduce the old
  names, including in `packaging/stratumoss/`, which is a deliberate tombstone.
- Provider plugins are located in `plugins/providers/`.
- Ensure new blueprints follow the schema defined in `profiles/templates/`.
- Do not use `# ` (hash followed by space) comment headers inside `llms.txt` quickstart code blocks, as it breaks the Invigil H1 count parser.
- Ensure exit codes for any new CLI commands are documented in `docs/api.md`.
- The CLI has memorable aliases: `bake`=`build`, `proof`=`validate`, `pantry`=`blueprints`
  (baking vocabulary — pre-configuring an image at build time is *baking*). **Write the
  canonical names** (`build`, `validate`, `blueprints`) in generated code and docs; accept
  either when parsing user input. Aliases are declared in `_ALIASES` in `bakex/cli.py` and
  resolved once in `main()` — if you add a subcommand alias, add it there too, or argparse
  will report the typed spelling and the command will fall through to the help text.
