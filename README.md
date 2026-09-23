# hong-cung-toi-radar

Social news radar for Hóng Cùng Tôi.

## Current pipeline

1. Collect Facebook social signals and trusted/official news.
2. Cluster signals into events.
3. Verify social-first stories against trusted sources.
4. Filter for concrete, newsworthy events.
5. Build `radar_editor_queue.json` for editorial handoff.
6. Publish approved Facebook Page posts with `facebook_publisher.py`.
7. Publish supplemental comments after the main post succeeds.

## Facebook Page publishing

See `FACEBOOK_PUBLISHER_V81.md`.

The publisher is intentionally separated from `radar.py` so discovery/editorial logic and production posting can evolve independently. The default publish queue committed to the repo is empty, and the GitHub Actions publisher workflow defaults to dry-run.

Required GitHub Secrets:

- `FB_PAGE_ID`
- `FB_PAGE_ACCESS_TOKEN`

The production Page token must include the permissions proven by the V8.1 test flow, including `pages_manage_posts`, `pages_manage_engagement`, `pages_read_engagement`, `pages_read_user_content`, and `pages_show_list`.


## Editorial Intelligence V8.2

V8.2 adds a second decision layer after factual verification.

`editorial_pipeline.py` reads `radar_events.json` and writes
`radar_editorial_v82.json` with:

- editorial score + tier (PRIORITY / GOOD / REVIEW / LOW)
- score breakdown: source strength, freshness, specificity, impact,
  human interest, discussion potential, visual potential, surprise
- risk flags for sensitive/legal/minor/health/political-or-official topics
- recommended editorial angle
- a strict drafting contract for the main post, comment chain, and source note
- an approval gate: nothing is sent to Facebook until `approved=true`

Important: the editorial score is a publishing-priority score, not a truth score.
Every item still requires reading the original source before drafting.

After an editor/LLM fills the `output_schema` fields and sets
`approved=true`, run:

```bash
python prepare_facebook_queue.py
```

This converts only approved items into `facebook_publish_queue.json`.
