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


## Manual Review V8.3 — no API cost

V8.3 keeps the AI drafting step inside the user's existing ChatGPT session instead of calling the OpenAI API from GitHub Actions.

Pipeline:

```text
Radar
-> Editorial V8.2
-> Original source reading
-> Draft packets
-> Manual review candidate list
-> User selects a story in ChatGPT
-> ChatGPT drafts A/B versions in the conversation
-> User reviews and explicitly approves
-> Approved content is written to facebook_publish_queue.json
-> Existing Facebook publisher workflow posts it
```

Key properties:

- no `OPENAI_API_KEY` is needed;
- no OpenAI API billing is introduced;
- GitHub Actions never asks a model to generate prose;
- no candidate is auto-approved;
- no candidate is auto-posted;
- the user remains the human approval gate.

### Prepare Manual Editorial Review V8.3

The workflow `Prepare Manual Editorial Review V8.3` runs Radar + V8.2, reads the original source, builds draft packets, then runs:

```bash
python build_manual_review_v83.py --limit 5
```

It creates:

- `editorial_review_candidates_v83.json`
- `editorial_review_candidates_v83.md`

The workflow also creates a GitHub Issue titled:

```text
[Editorial Review V8.3] Run <run_id>
```

The issue contains the top candidate stories, editorial score, monetization risk, risk flags, source title and source URL.

### ChatGPT handoff

After reviewing the issue, the user can say in ChatGPT:

```text
Biên tập tin số 2
```

or provide the `event_id`.

ChatGPT then reads/validates the original source again and prepares the Facebook draft. Only after the user explicitly says **duyệt đăng** should the approved text be written into `facebook_publish_queue.json`.

The existing Facebook publisher remains a separate workflow and can still be run in dry-run mode before a real Page post.


## Windows laptop Facebook collector

Authenticated Facebook collection is now separated from the always-on cloud radar.

- Cloud radar continues news-first collection without the laptop.
- A Windows laptop can run `facebook_collector_agent.py` with a persistent logged-in Chromium profile.
- The collector writes `radar_fb_local.json`, which cloud Radar consumes as a fresh social-signal bridge.
- Social captions remain discovery signals only; factual claims still require official/trusted-source verification.
- The laptop setup/migration guide is in `LAPTOP_MIGRATION.md`.
