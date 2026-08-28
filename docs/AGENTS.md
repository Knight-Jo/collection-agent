# Documentation Rules

These rules apply to `docs/` and keep project documentation current,
discoverable, and small.

## Classification

| Directory | Contents |
| --- | --- |
| `architecture/` | Current architecture, stable policies, and cross-module invariants |
| `development/` | Developer guidance, deployment operations, and active acceptance plans |
| `reports/` | Current capability, progress, value, and evaluation reports |
| `presentations/` | Current HTML presentations; keep at most one management and one technical deck |

Keep only `AGENTS.md` and an optional navigation `README.md` directly under
`docs/`. Put new documents in the directory matching their primary purpose.
Architectural decisions belong in the authoritative architecture document;
introduce ADR files only when decisions require an independent lifecycle.

## Maintenance

1. Update an existing authoritative document instead of creating a dated or
   renamed copy.
2. Delete superseded designs and completed implementation plans. Git history
   preserves them; experiment-reproducibility records belong in `experiments/`.
3. Keep Markdown as the authoritative source. HTML is a presentation output,
   not a second technical specification.
4. Keep no more than two current HTML decks: one management briefing and one
   technical briefing. Replace or delete an older deck when adding a new one.
5. Store experiment manifests, traces, snapshots, and generated reports under
   `experiments/`; do not copy them into `docs/`.
6. Support measured claims with a run ID, date, data source, and metric
   definition. Mark targets as targets rather than achieved results.
7. Use repository-relative links and update every inbound link when moving a
   document. Verify referenced commands and source paths against the current
   tree.
8. Prefer concise English kebab-case names for new files. Existing stable links
   may keep their names until the document is substantially revised.
9. Before merging, remove temporary drafts, duplicate introductions, obsolete
   screenshots, machine-specific paths, and unsupported claims.
10. Do not introduce another top-level documentation category without first
    proving that none of the four current categories fits.
