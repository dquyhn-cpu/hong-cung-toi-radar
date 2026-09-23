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
