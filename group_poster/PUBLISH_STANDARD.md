# Hóng Cùng Tôi — Canonical Group Publish Pipeline

This is the required production path for every new post.

1. Finalize the verified article text.
2. Finalize/create the image.
3. Stage the image into `facebook_assets_b64/` as base64 chunks + manifest.
4. Package MUST reference `image_asset_name` and MUST NOT depend on `image_url` at publish time.
5. Commit package and staged asset first.
6. Only after staging is complete, update `group_poster/group_queue.json` with a new command_id.
7. Windows agent pulls, rebuilds the local asset, validates the package, then starts Chromium.
8. Chromium's job is Facebook only: open group -> composer -> Page identity -> attach local image -> caption -> submit.
9. Publish status is accepted only from agent state/report, not merely from a queued commit.

Operational rule: do not ask the user to run PowerShell during normal publishing. PowerShell is reserved for exceptional agent/service repair only.

Default pacing: 15 seconds between groups unless a specific post needs a more conservative delay.
