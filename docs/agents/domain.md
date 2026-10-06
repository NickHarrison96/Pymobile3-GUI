# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists: it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill creates them lazily when terms or decisions actually get resolved.

## Layout

**Single-context.** One `CONTEXT.md` and one `docs/adr/` at the repo root — this is a single Python package (`pymobile3_gui/`) with no workspace or multi-package split.

## Repo-specific note: `AGENTS.md` is the domain doc here

There is no `CONTEXT.md` and no `docs/adr/` yet, but **`AGENTS.md` already plays
the role** and must be read before exploring. It carries:

- the architecture tree and where each subsystem lives
- the threading model and the "never touch widgets from non-GUI threads" rule
- task-system conventions (step names must match declared lists exactly)
- **"Learned Pitfalls"** — the accumulated hard-won constraints, and the most
  valuable thing in the repo. Windows/USB quirks, the cp1252 console encoding
  trap, exit-0-but-failed commands, WSL argv rewriting, asset-path resolution.

Treat those pitfalls as binding. Several describe bugs that were already fixed
once and cost hours; reintroducing the pattern means re-debugging it.

Two documents sit alongside it and are equally load-bearing:

- **`docs/REFERENCES.md`** — provenance for every reference implementation and
  upstream project, plus the licensing rules. Read before porting or vendoring
  anything.
- **`docs/TODO.md`** — the active roadmap. §6 covers the Legacy iOS Kit feature
  parity work, including which parts are deliberately *not* being ported.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in these docs. Don't drift to synonyms the glossary explicitly avoids.

Established vocabulary worth matching exactly:

| Term | Means |
|---|---|
| workspace | One of the six full-page views in `views/` |
| operation | A named device action exposed by a backend `op_*` function |
| step | One entry of a declared `steps` list; worker `step=` strings must match exactly |
| task | One run of `TaskManager.start_task(...)`, with its own `task_id` |
| capability database | The `device_db.py` data tables gating which actions are offered |
| signed-OTA matrix | The 6.1.3 / 8.4.1 / 10.3.3 versions Apple still signs |

If the concept you need isn't defined yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing decision recorded in `AGENTS.md` or `docs/TODO.md`, surface it explicitly rather than silently overriding:

> _Contradicts the recorded constraint in AGENTS.md ("DFU over USB on Windows") that Apple's driver binds the interface exclusively, but worth revisiting because…_
