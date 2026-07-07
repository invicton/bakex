## What does this PR do?

<!-- One or two sentences. -->

## Why

<!-- The problem or gap this addresses. -->

## Testing

<!-- How did you verify this? -->
- [ ] `uv run pytest` passes locally
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] Added/updated tests for the change (see `docs/test_plan.md` for the
      project's TDD conventions)
- [ ] If this touches a cloud provider: ran against a real provider, or
      explained why that isn't practical for this change
- [ ] If this adds or changes a blueprint: the "Validate community blueprints"
      check passes (schema + `blueprints/index.json` consistency)

## Checklist

- [ ] I've read `CONTRIBUTING.md`
- [ ] This PR is scoped to one logical change
- [ ] I've updated `CHANGELOG.md` if this is user-visible
- [ ] All commits are signed off (`git commit -s`) per the
      [DCO](https://developercertificate.org/)
