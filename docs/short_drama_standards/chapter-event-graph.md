# Chapter Event Graph Asset

This is the asset-only stage for long-form short-drama adaptation. It adds a
reviewable chapter event graph asset without changing runtime schemas or prompt
builders.

## Scope

- Create or edit `drafts/chapter-events.json` as a draft artifact.
- Keep the graph under manual review before it influences episode planning or
  script rewriting.
- Use event summaries to avoid feeding full source text into every downstream
  prompt.

## Non-goals

- Schema changes are deferred. Do not add `act`, `character_ids`, `prop_ids`, or
  other new script fields in this asset-only stage.
- Do not automatically inject the graph into generation prompts.
- Do not call Claude, provider APIs, media generation, queues, exports, or review
  confirmation tools.

## Minimal JSON shape

```json
{
  "schema_version": 1,
  "artifact_type": "chapter_event_graph",
  "status": "draft_pending_review",
  "source_files": ["source/novel.txt"],
  "chapters": [
    {
      "chapter_id": "C01",
      "chapter_name": "...",
      "events": [
        {
          "event_id": "C01E01",
          "summary": "...",
          "characters": [],
          "scenes": [],
          "props": [],
          "emotion": "...",
          "causal_prev": [],
          "temporal_order": 1
        }
      ]
    }
  ],
  "cross_chapter_arcs": [],
  "manual_review": { "reviewed": false, "review_notes": "" }
}
```

## Review checklist

Before using the graph as context, a human reviewer should confirm:

1. Each event is a concise, filmable unit rather than a prose dump.
2. Critical characters, scenes, props, and clues are not lost.
3. Cross-chapter arcs capture motivation shifts, payoffs, and episode-end hooks.
4. The graph remains a draft artifact until the next planning or rewriting step
   explicitly opts in to use it.
