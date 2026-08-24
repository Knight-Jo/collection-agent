# Documentation Rules

These rules apply to `docs/` and keep project documentation current,
discoverable, and small.

## Classification

| Directory | Contents |
| --- | --- |
| `standards/` | Stable policies, terminology, and engineering rules |
| `architecture/` | Current system architecture and cross-module design |
| `plans/` | Approved roadmaps, implementation guidance, and acceptance plans |
| `evaluations/` | Evaluation methods and evidence-based run/model comparisons |
| `reports/` | Current written project, capability, progress, and value reports |
| `presentations/` | Current HTML presentations; keep at most one management and one technical deck |
| `operations/` | Deployment, runtime, and troubleshooting guidance |
| `archive/<year>/` | Historical material that must remain available for audit or contract reasons |
| `agents/` | Instructions used by coding agents |
| `superpowers/` | Skill-generated specifications and implementation plans |

Keep only `AGENTS.md` and an optional navigation `README.md` directly under
`docs/`. Put new documents in the directory matching their primary purpose.
Use `docs/adr/` for architectural decisions when that directory is introduced.

## Maintenance

1. Update an existing authoritative document instead of creating a dated or
   renamed copy.
2. Delete superseded material unless it is required for audit, contract, or
   experiment reproducibility. Put material meeting that exception under
   `archive/<year>/` and state why it is retained.
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
