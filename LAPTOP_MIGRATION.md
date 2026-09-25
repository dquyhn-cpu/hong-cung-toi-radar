# LAPTOP MIGRATION - HONG CUNG TOI

## Architecture after migration

The system is split into two layers.

1. Cloud/GitHub Actions keeps the news-first radar running when the laptop is off.
2. The Windows laptop runs authenticated Facebook collection and Facebook group publishing while the laptop is on.

The Facebook collector uses the same source list already defined in radar.py. Current social-radar sources include BeatVN, Theanh28, Top Comments and Bi Mat Showbiz. Official Facebook sources are also collected.

Social captions are trend signals only. Facts still have to be verified against official or trusted news sources before editorial handoff.

## One-time setup on the new laptop

Clone the repository, open PowerShell in the repository folder, then run:

Set-ExecutionPolicy -Scope Process Bypass
.\windows\setup_laptop.ps1

The setup checks or installs Git and Python, installs requirements, installs Playwright Chromium, and creates these Windows tasks:

- HongCungToiGroupPosterAgent
- HongCungToiFacebookCollector

## One-time Facebook login

Radar collector:

python facebook_collector_local.py --login

Group Poster:

python group_poster\group_poster.py --login

They intentionally use separate persistent browser profiles.

## Facebook bridge

The laptop collector writes:

- radar_fb_local.json
- radar_fb_local_diagnostics.json

It pushes those files to GitHub. Cloud Radar loads radar_fb_local.json only while the snapshot is fresh. The current freshness window is 8 hours.

Cloud Radar then merges local Facebook posts with its own cloud signals, deduplicates events, and verifies social-first stories against trusted sources.

## Manual collector test

python facebook_collector_local.py --headless --push

Expected output contains a count for each Facebook source. If one source returns zero, inspect radar_fb_local_diagnostics.json.

## When the laptop is off

- Cloud news radar continues.
- Direct authenticated Facebook collection pauses.
- Group posting pauses.
- The most recent Facebook snapshot remains usable only until its freshness window expires.

## Migration rule

Do not run the old desktop and the new laptop as Group Poster agents at the same time. Once the laptop is verified, disable HongCungToiGroupPosterAgent and HongCungToiFacebookCollector on the old desktop to avoid duplicate work.
