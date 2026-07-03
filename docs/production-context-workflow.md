# Production Context / Project Bible Workflow

Production Context is a project-local sidecar for manual short-drama production
memory. It stores a small Project Bible, explicit step-context preferences, human
revision memory, and a checklist next to `project.json` as:

```text
projects/<project>/production_context.json
```

A missing file is valid. The API returns defaults without writing anything until
a human saves context or appends revision memory.

## Manual-only policy

The sidecar is not hidden prompt injection and does not start Claude, Ark,
Jimeng, Dreamina, Seedance, exports, or generation queues. Use
`injection-snippet` to copy a snippet into the next draft prompt only when a
human explicitly chooses to include it.

## API

All routes are under `/api/v1`:

```http
GET  /projects/{project_name}/production-context
PUT  /projects/{project_name}/production-context
POST /projects/{project_name}/production-context/revisions
POST /projects/{project_name}/production-context/injection-snippet
```

## Suggested use

1. Maintain logline, tone, visual style, world rules, anchors, and negative
   constraints in the Project Bible.
2. After a manual review or failed attempt, append revision memory with the human
   critique and next fix strategy.
3. Generate a manual opt-in snippet and paste it into a Claude draft or provider
   prompt only when useful for the current step.
