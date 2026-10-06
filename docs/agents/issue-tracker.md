# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues in
`NickHarrison96/Pymobile3-GUI`. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v`; `gh` does this automatically when run inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Repo-specific caution — do not leak device data

This is a forensics and security tool. An issue body is public and cannot be
retracted once pushed.

**Never include** in an issue body, comment, or pasted command output:

- UDIDs, ECIDs, serial numbers, or `AppleDeviceName` values
- Extracted user data, backups, crash-report contents, DCIM media
- IPSW contents, SHSH blobs, activation records, baseband dumps
- Anything from a real device's lockdown/AFC filesystem

Refer to devices by marketing model and iOS version only ("iPhone10,4 on
iOS 16.0.3"). When a bug needs real identifiers to reproduce, say so in the
issue and let the reporter supply them privately.

The same caution applies to log files. `logs_dir()` writes crash-handler logs
that can contain device strings — check before attaching.
