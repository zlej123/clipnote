# clipnote

Turns videos into documents, recipes, and user manuals.

Instructions like *"cut it bite-sized"* or *"simmer until the sauce reduces"* don't mean much as text. clipnote finds the frame where that state is actually visible and embeds it next to the step. It works across domains — cooking, repair, crafts, beauty, fitness, software — and exports to Notion, Obsidian, and Goodnotes.

Gemini analyzes the video itself (visuals and audio), so it works on videos without captions, and when the narration runs ahead of the action.

This repo is the Python core and the language-neutral `skill-core/` assets. If you just want to use
clipnote, the clients built on it are [clipnote-apple](https://github.com/zlej123/clipnote-apple)
(iOS/iPadOS/macOS) and [clipnote-extension](https://github.com/zlej123/clipnote-extension) (Chrome).

## Example

Generated from [this pork stir-fry video](https://youtu.be/4ioPBiTWm3M). Where the video only says *"simmer until the sauce reduces"*, the document reads:

> 2\. **Simmer the pork in the sauce**
> - Add 1/2 cup water, 1T brown sugar, 1T syrup to the pan; once dissolved, add the pork. …
> - 💡 *"Reduced" means:* almost no liquid left on the pan bottom, sauce clinging to the meat with a glossy sheen.
>
> ![reduced sauce state](docs/demo/demo-state.jpg)

And *"cut it bite-sized"*:

> - 💡 *"Bite-sized" means:* roughly 3–4 cm cubes.
>
> ![bite-sized pork](docs/demo/demo-size.jpg)

## Install

```bash
pip install -e .                   # installs deps + the `clipnote` command
# system dependency: ffmpeg (on PATH; not needed for --links-only)
export GEMINI_API_KEY=...          # Google AI Studio key
```

## Usage

One command runs the whole pipeline.

```bash
# 1) Fully automatic, links instead of screenshots (no ffmpeg)
clipnote "https://www.youtube.com/watch?v=..." --profile generic --language en --links-only

# 2) Fully automatic with screenshots: AI picks the frames, you review after
clipnote "https://www.youtube.com/watch?v=..." --profile recipe --language en --auto-pick --export goodnotes

# 3) Manual frame selection
clipnote "https://www.youtube.com/watch?v=..." --profile recipe --language en
#   → open the printed picker.html, pick one candidate per guide, save picks.json
clipnote "https://www.youtube.com/watch?v=..." --profile recipe --language en \
    --picks work/frames/<id>/recipe.en/picks.json --export goodnotes
```

Options: `--profile generic|recipe`, `--language ko|en|ja|...`, `--max-guides N`, `--model`, `--auto-pick`, `--export bundle|obsidian|goodnotes|notion` (Notion also needs `--parent <page-id>` and `NOTION_TOKEN`).

With `--auto-pick`, Gemini vision chooses among the three candidates per guide (or falls back to a
timestamp link when none fits). The regenerated picker.html shows the AI picks pre-selected; if you
correct any, download the evaluation file and record it:

```bash
python -m clipnote.feedback add semantic-evaluation.json   # accumulates accuracy + disagreement patterns
```

Artifacts are written under the current directory (override with `CLIPNOTE_DATA`).

## Note app export

| Target | How | Status |
|--------|-----|--------|
| Obsidian | Markdown + attachments copied into a vault folder | done |
| Goodnotes | PDF (CJK fonts supported) for the import/share flow | done |
| Notion | direct upload via the Notion API (your integration token) | done |

```bash
clipnote-export <id> --profile recipe --language en --target obsidian --destination /path/to/vault
clipnote-export <id> --profile recipe --language en --target goodnotes
NOTION_TOKEN=... clipnote-export <id> --profile recipe --language en --target notion --parent <page-id>
```

## Reusing clipnote

Two reuse boundaries:

1. **`skill-core/`** — language-neutral assets: `profiles/<name>/{prompt.md, schema.json, template.md}` and `engine/rules.md`. Any platform can consume these as data.
2. **The Python modules** — reusable wherever Python runs.

| Consumer | How |
|----------|-----|
| REST API server | wraps the modules — see [clipnote-server](https://github.com/zlej123/clipnote-server) |
| Desktop app / Python tools / agent skills | import directly (see `skills/clipnote/SKILL.md`) |
| iOS/iPadOS/macOS app | [clipnote-apple](https://github.com/zlej123/clipnote-apple) — bundles `skill-core/` and calls Gemini directly (no server), with the Python renderer ported to Swift |
| Browser | [clipnote-extension](https://github.com/zlej123/clipnote-extension) — captures frames from the YouTube player itself |

Both clients capture frames on their own side (WKWebView / canvas), so neither needs ffmpeg or a
download step, and the server stays optional. clipnote-apple is the fullest reuse of `skill-core/`:
its Swift port of the mustache renderer is pinned to this repo's `render.py` output by golden tests,
so a template change here stays reproducible there.

## Use as an agent skill

clipnote ships as an agent skill (`skills/clipnote/SKILL.md`).

- **Claude Code**: `/plugin marketplace add zlej123/clipnote`, then `/plugin install clipnote@clipnote`.
- **Manual**: copy `skills/clipnote/` into your skills directory (`~/.claude/skills/` or `~/.gjc/skills/`).

The skill clones this repo on first use and asks for a Gemini API key if none is set.

## Adding a domain profile

Drop three files into `src/clipnote/skill-core/profiles/<name>/`: `prompt.md` (containing `{{RULES}}`), `schema.json`, `template.md`. No pipeline changes needed.

## Tests

```bash
python -m unittest discover -s tests        # contract / normalization / selection / export
python tests/validate_fixtures.py --online  # fixture availability + strata
python tests/batch.py                        # 6-domain structural + semantic regression
```

`tests/fixtures/urls.json` is a regression corpus of 8–12 videos per domain, stratified by length, audio, captions, editing style, framing, and source language.

## Limits

- Public videos only; under 30 minutes recommended.
- Free-tier Gemini rate-limits under batch load. Default model is `gemini-flash-lite-latest`.
- Timestamps are accurate to about ±2–3 s; the before/center/after candidates cover the gap.
- Not useful for videos with nothing visual to show (lectures, vlogs, reviews).

## License

MIT
