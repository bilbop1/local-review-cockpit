# Campaign Selection Standard

Campaign choice decides whether the pipeline produces real clips or polished filler. Use this file before indexing, sourcing, or rendering.

## Good Campaigns

Prioritize campaigns with:

- Streamer-native or creator-native content.
- Daily or near-daily source supply.
- Public clips, VODs, or source packs with a verifiable route.
- Clear campaign brief, source permission expectations, and platform targets.
- Moments that stand alone without long setup.
- Enough source velocity to reject most candidates.
- Obvious viewer reason to watch, react, laugh, argue, or share.

## Weak Campaigns

Avoid or demote campaigns with:

- Brand/product explainers that do not have an organic hook.
- No linked media pack and no official/public source route.
- Briefs that require making new content rather than clipping source media.
- Criteria so narrow that normal daily clips do not qualify.
- No reason a TikTok/Reels/Shorts viewer would stop scrolling.

If a campaign does not provide media and has no verifiable source route, mark it blocked. Do not content-generate filler for a clipping campaign.

## Current Defaults

Active streamer-first targets:

- YourRAGE: `https://clipping.net/dashboard/campaigns/yourrage-x-clipping`
- PlaqueBoyMax: `https://clipping.net/dashboard/campaigns/plaqueboymax-x-clipping`
- JasonTheWeen: `https://clipping.net/dashboard/campaigns/jasontheween-x-clipping`

Demoted or excluded:

- Lacy: demoted unless the clip actually satisfies the arrested/missing-in-action brief.
- Haste: excluded unless a real linked source pack or verified source route appears.
- Kalshi/Dunkman: archived from the streamer-first default lane.
- Doublelift: watchlist until budget/freshness/source status is reconfirmed.

## Source Proof

A source is not verified because a title exists. Production candidates require:

- Campaign rules stored.
- Source URL stored.
- Source route/provenance stored.
- Local media file present.
- Word-timed transcript present.
- Rendered kit sidecars present.
- Editorial review present.

Metadata-only candidates can remain indexed, but they cannot count as review proof.

## Fresh Clip Indexing

For active streamer campaigns, index fresh supply in this exact order:

1. Last 24 hours.
2. Last 48 hours if 24h is empty, stale, or too thin.
3. Last 72 hours if 48h is still thin.
4. Last 4 days.
5. Last 5 days.

Do not use the old 35-day top-recent sweep as normal production proof. It is an emergency/manual research fallback only. Rank candidates by views, freshness, campaign fit, hook strength, source quality, duplicate avoidance, and recent rejection-learning penalties.

Top-card copy is gated before render. A campaign kit must use a hook shaped like streamer/person + situation + tension, and the deterministic gate blocks generic chat filler, quote dumps, raw-title echoes, duplicates from the recent campaign queue, internal labels, and hooks that are too short or too long. `blocked_hook_quality` means Hermes should pick a better candidate or propose better hook copy; it is not permission to hand-curate the same bad card into Review Kits.

## Daily Review Factory

Default production rhythm is three active campaigns, one review kit per campaign every three hours, capped at eight kits per campaign and 24 total per local day. The operator is expected to approve some and kill others with notes. Killed kits are learning signal for the next cycle, not drafts to polish.

## Editorial Floors

Default floors until the operator changes them:

- YourRAGE: 1,350 views.
- PlaqueBoyMax: 1,500 views.
- JasonTheWeen: 2,000 views.
- Maximum automatic duration: 52 seconds unless a deliberate cut is stored.

Prefer fewer strong review kits over padded numeric targets. If there are not enough strong candidates, readiness should stay yellow.
