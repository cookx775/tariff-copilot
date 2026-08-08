# Domain Docs

This repository uses a single domain context.

## Before exploring

Read these artifacts when they exist:

- `CONTEXT.md` at the repository root.
- Relevant architectural decision records under `docs/adr/`.

If they do not exist, proceed silently. Create them lazily only when domain terminology or a qualifying architectural decision is actually resolved.

## Domain vocabulary

Use the canonical terms defined in `CONTEXT.md` in issue titles, specifications, tests, and code. If required vocabulary is absent, determine whether the term represents a real domain gap before adding it.

## Architectural decisions

Surface any conflict with an existing ADR rather than silently overriding it. Create an ADR only for a decision that is costly to reverse, surprising without context, and the result of a genuine trade-off.
