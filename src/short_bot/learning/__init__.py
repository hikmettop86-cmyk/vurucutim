"""Performance-feedback-loop machinery.

Aggregates YouTube stats for past uploads into per-channel insights:
top categories, watch%-leaders, top-view examples, mood distribution,
headline-keyword frequencies. Output is consumed by:

- `/insights/<slug>` web page (display)
- Scorer prompt injection (next-run guidance)
- Nightly cron job that pre-computes + caches the JSON in DB

The aggregator only counts shorts that:
- Belong to the requested channel
- Have a successful `youtube_uploads` row
- Have at least one `youtube_video_stats` snapshot

So very recent uploads (<48h, no stats yet) won't move the insights —
the YT Analytics delay is intentional, recommendations only fire once
the data has settled.
"""
