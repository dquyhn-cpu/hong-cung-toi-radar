# FACEBOOK GROUP PUBLISHER — SEPARATE TOOL

This subsystem is intentionally isolated from Page publishing.

Files:
- facebook_group_capability_test.py
- .github/workflows/facebook-group-capability-test.yml

Rules:
- Never modify facebook_publisher_fast.py for Group support.
- Never reuse .facebook-publish-trigger for Group operations.
- Capability test is read-only and must not create posts/comments.
- Group publishing, if later supported, must use a separate queue, separate workflow, and separate state.
- Page package may be reused only after PAGE_VERIFIED / GROUP_READY.
