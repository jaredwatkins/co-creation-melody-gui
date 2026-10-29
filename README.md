# Human–AI Co-Creation in Melody Writing

A MIDI-native co-writing system for studying human–AI melodic collaboration,
built on Stanford's [Anticipatory Music Transformer](https://github.com/jthickstun/anticipation)
(`stanford-crfm/music-small-800k`). This repo accompanies the paper
*Human–AI Co-Creation in Melody Writing: A MIDI-Native Pilot on Flow,
Authorship, and Control* — [preprint](https://doi.org/10.33767/osf.io/zwtgp_v1) ·
[peer-reviewed artifact](https://doi.org/10.17605/OSF.IO/P3HQG).

## The app

A local web app with a piano-roll editor implementing the paper's bar-aligned
co-creation loop:

- **Piano-roll editor** — draw, move, resize, and erase notes on a bar-aligned
  grid; snap to 1/16–bar.
- **AI turn** — "Continue with AI" generates the next N bars with the
  anticipatory transformer. Notes you write *ahead* of the cursor are treated
  as anticipated controls — the model fills toward them. Drafts appear ghosted
  until you **Keep** or **Discard** them.
- **Human vs. model provenance** — human notes blue, model notes orange.
- **Playback** — in-browser WebAudio synthesis (no FluidSynth needed), MIDI
  keyboard input via Web MIDI.
- **V0–V3 snapshots** — one-click standardized version exports per the study
  protocol, each downloadable as `.mid` or restorable.
- **Study log** — every edit, generation, accept/discard, snapshot and export
  is appended to a per-session `events.jsonl` for reproducible analysis.

## Run it

```bash
pip install -e .
cocreate          # serves the UI and opens your browser
```

Python 3.9+. The `stanford-crfm/music-small-800k` weights (~500 MB) download
to the HuggingFace cache on first run. Generation runs on CUDA / Apple-Silicon
MPS when available, CPU otherwise.

Terminal-only generation is still available:

```bash
python run_anticipation.py --input seed.mid --seconds 10 --output out.mid
```

## Downloadable app (macOS)

Install the latest release with one Terminal line (recommended — `curl`
downloads carry no quarantine flag, so the app installs and opens with no
Gatekeeper prompts):

```bash
curl -fsSL https://raw.githubusercontent.com/jaredwatkins/co-creation-melody-gui/main/install.sh | bash
```

Or download `CoCreate-installer.pkg` / `CoCreate.dmg` from
[Releases](https://github.com/jaredwatkins/co-creation-melody-gui/releases)
manually — unsigned builds are blocked until you allow them in
System Settings → Privacy & Security → Open Anyway, or remove the flag with
`xattr -dr com.apple.quarantine <file>`.

Build locally:

```bash
./packaging/build_macos.sh          # -> dist/CoCreate.dmg
./packaging/build_macos.sh --pkg    # also dist/CoCreate-installer.pkg
```

Produces `CoCreate.app` via PyInstaller (torch included; the bundle is large)
wrapped in a `.dmg` and optional `.pkg` installer. The app renders the GUI in
its own native window — no browser tab, no HTTPS-Only warnings. Pushing a `v*`
tag runs the
same build on a macOS GitHub Actions runner and attaches the artifacts to a
GitHub Release — see `.github/workflows/release.yml`.

## Layout

    cocreation/          the web app (FastAPI backend + vanilla-JS frontend)
    anticipation/        vendored Stanford Anticipatory Music Transformer (Apache-2.0)
    experiments/         upstream humaneval scripts the pilot was based on
    legacy/              early Magenta experiments (unsupported — see legacy/README.md)
    tests/               unit + API tests (pytest)
    packaging/           PyInstaller spec and macOS build script

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT for the application code (© 2025 Jared Watkins). `anticipation/` is a
vendored copy of Stanford's Apache-2.0-licensed package — see
`anticipation/LICENSE.txt` and `anticipation/UPSTREAM.md`.
