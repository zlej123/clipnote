---
name: clipnote
description: Turn a how-to YouTube video into a follow-along document where ambiguous spoken instructions ("bite-sized", "until it reduces") are backed by the exact video frames that show them. Use when the user shares a YouTube how-to/tutorial URL and wants a clean visual guide document, optionally exported to Notion/Obsidian/Goodnotes.
---

# clipnote

<Purpose>
Convert a how-to YouTube video into a follow-along document where every vague verbal instruction
("bite-sized", "until the sauce reduces", "fold it here") is backed by the exact video frame that
shows it. Works across domains (cooking, DIY/repair, craft, beauty, fitness, software tutorials)
via swappable profiles. Output is a portable document that exports to Notion, Obsidian, or Goodnotes.
</Purpose>

<Use_When>
- User shares a YouTube how-to URL and wants a clean, followable text/visual guide.
- User complains that a tutorial's spoken directions are ambiguous and wants the "show me" frame.
- User wants a recipe/procedure saved into a notes app.
</Use_When>

<Do_Not_Use_When>
- Video is a talking-head lecture, vlog, review, or podcast with no visually-resolvable actions.
- Content is safety-critical (medical, mains electricity, gas, heavy machinery) — needs an expert-reviewed profile.
</Do_Not_Use_When>

<Prerequisites>
- The clipnote repo on disk. If absent, clone it first:
  `git clone https://github.com/zlej123/clipnote` and run all commands from that directory.
- Environment variable `GEMINI_API_KEY` (Google AI Studio key). If missing, ask the user for one
  (free at https://aistudio.google.com/apikey) — never proceed without it.
- `ffmpeg` on PATH (frame capture; not needed for `--links-only`).
- `pip install -e .` from the repo (installs deps and the `clipnote` command).
</Prerequisites>

<Contract>
The analysis JSON is the stable boundary. Steps carry procedure only; every ambiguous moment is an
independent entry in a top-level `visual_guides[]` array, each linked to a `step_id`, typed
(size/thickness/color/state/amount/position/angle/action/texture), and pointing at
`best_visual_timestamp`. `contract.py` enforces: ≤ `max_visual_guides`, timestamps within duration,
valid step references, non-vague `guide_text`. Output language follows the user profile
(`--language`).
</Contract>

<How_To_Run>
One command drives analyze → capture → pick → render → export.

1. Fully automatic (no ffmpeg, timestamp links instead of screenshots):
   `clipnote <URL> --profile generic --language ko --links-only`

2. Fully automatic with screenshots (Gemini picks the frame per guide):
   `clipnote <URL> --profile recipe --language ko --auto-pick --export goodnotes`
   Review the regenerated `picker.html` (AI picks pre-selected); if the user corrects any,
   run `python -m clipnote.feedback add <semantic-evaluation.json>` to log it.

3. Manual/agent frame selection:
   - `clipnote <URL> --profile recipe --language ko`
   - Agent path: read the three candidate frames under `work/frames/…` directly, write
     `picks.json` yourself (semantic judgment), then re-run with
     `--picks <picks.json> --export goodnotes` (or `obsidian`/`bundle`/`notion`).

Notion export needs `NOTION_TOKEN` and `--parent <page-id>`.
Artifacts go under the current directory (`CLIPNOTE_DATA` overrides).
</How_To_Run>

<Profiles>
- `generic`: any how-to (materials + steps + visual guides).
- `recipe`: cooking-tuned (adds servings, ingredient wording).
- Add a domain by dropping `src/clipnote/skill-core/profiles/<name>/{prompt.md,schema.json,template.md}`.
</Profiles>

<Outputs>
- `work/analyses/<id>/<profile>.<language>.json` — validated analysis.
- `work/frames/<id>/<profile>.<language>/` — 3 candidates per guide + picker.html.
- `output/<id>/<profile>.<language>/document.md` (+ images/).
- `exports/<id>/<profile>.<language>/{bundle|goodnotes}/…` — note-app artifacts.
</Outputs>

<Verification>
- `python -m unittest discover -s tests` — contract/normalize/selection/export unit tests.
- `python tests/batch.py` — structural + semantic regression over the fixture corpus.
- `python tests/validate_fixtures.py --online` — fixture URL availability + strata.
</Verification>

<Limits>
- Public videos only; ≤ ~30 min recommended for cost/time.
- Free-tier Gemini rate-limits under batch load; default model is `gemini-flash-lite-latest`.
- Timestamp accuracy ±2-3s is covered by the before/center/after candidates.
</Limits>
