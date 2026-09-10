# Domain Docs

This repository has one domain context: [CONTEXT.md](../../CONTEXT.md).
Read it before exploring or changing domain behavior, and use its vocabulary.

For current entry points and module ownership, start with
[README.md](../../README.md). Specifications under `specs/` describe requirements;
verify implementation status against source and tests rather than treating a
design or historical report as proof of delivery.

If a change affects a domain term or invariant, update `CONTEXT.md` and the
relevant authoritative document. Surface conflicts explicitly rather than
silently redefining a term. Do not create parallel context maps or ADR trees
unless the project actually needs them; follow [documentation rules](../AGENTS.md).
