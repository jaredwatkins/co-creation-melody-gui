# Devin Teammate Onboarding

You're joining an existing effort. Read this whole file first — the "Hard rules"
and "Landmines" sections prevent repeating painful mistakes.

## What this project is

A GUI + macOS packaging effort for a Stanford-model human–AI melody co-creation
research app (the owner's PhD admission artifact). Paper:
https://doi.org/10.33767/osf.io/zwtgp_v1 · https://doi.org/10.17605/OSF.IO/P3HQG

- **Work repo:** `jaredwatkins/co-creation-melody-gui` (public) — everything happens here, on `main`.
- **NEVER modify the original repo** `jaredwatkins/Human-AI-Co-Creation-in-Melody-Writing---A-MIDI-Native-Pilot-on-Flow-Authorship-and-Control`. The user was explicit: it stays untouched.

## Repo layout

- `cocreation/` — the app: FastAPI server (`server.py`), model wrapper (`engine.py`
  around `stanford-crfm/music-small-800k`, lazy-loaded), session store (`store.py`),
  static UI (`static/` — vanilla-JS piano roll: `pianoroll.js`, `app.js`, `audio.js`).
- `anticipation/` — vendored Stanford Anticipation code (not on PyPI; keep it vendored).
- `packaging/` — `entry.py` (frozen-app entry: single-instance lock, window lifecycle,
  server thread, native save API), `cocreate.spec` (PyInstaller), `build_macos.sh`.
- `.github/workflows/release.yml` — tag `v*` → builds `dist/CoCreate-installer.pkg`
  on **macos-15** (macos-14 is retired — jobs cancel instantly), uploads **only the .pkg**.
- `.github/workflows/test.yml` — ubuntu-latest, runs pytest.
- `tests/` — `pytest tests/` (11 tests currently).
- `install.sh` — end-user one-liner: downloads latest pkg → `sudo installer` → strips
  quarantine → opens.

## Local dev

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt -e .
.venv/bin/python -m pytest tests/ -x -q
.venv/bin/cocreate            # dev server, opens http://127.0.0.1:<port> in browser
```

First run downloads ~500MB of model weights from HF.

## Release pipeline

```bash
git tag v0.1.X && git push origin v0.1.X   # triggers the macos-15 build
```

- Stamp version step writes `cocreation/VERSION` (shown in the app header as `· vX.Y.Z`
  and in the About box via `CFBundleShortVersionString`).
- Convention: **exactly one release** — after each new release publishes, delete the
  previous release AND its tag so `/releases/latest` is always current.
- Releases carry **only `CoCreate-installer.pkg`** (user prefers pkg; dmg was dropped).
- GitHub API calls need `Authorization: Bearer $GITHUB_PAT_COCREATION`
  (user-provided PAT, `repo`+`workflow` scopes); unauthenticated calls 403.

## Hard rules

- **Commit attribution:** every commit as `Jared Watkins <jared@88thstreetrecords.com>`
  with NO `Co-Authored-By` trailer and no AI/Devin mention anywhere (commits, releases,
  app UI). Devin's `git` shell wrapper injects its own identity+trailer — bypass it:
  `/usr/bin/git commit` with `GIT_AUTHOR_NAME/EMAIL` and `GIT_COMMITTER_NAME/EMAIL` env vars.
- **All shell commands sent to the user go in fenced code blocks.** He's a musician/
  researcher, not a developer — numbered steps, copyable commands, explain mechanics plainly.
- User's standard install/test command:

  ```
  pkill -f CoCreate; curl -fL -o /tmp/CoCreate-installer.pkg "https://github.com/jaredwatkins/co-creation-melody-gui/releases/latest/download/CoCreate-installer.pkg" && sudo installer -pkg /tmp/CoCreate-installer.pkg -target / && open /Applications/CoCreate.app
  ```

  Always download fresh to `/tmp` — `~/Downloads/CoCreate-installer.pkg` is whatever
  OLD file is already there (same filename every release), and installing it silently
  downgrades to an ancient build.

## Landmines already stepped on (don't re-diagnose)

1. **"Infinite reopen" loop (fixed in v0.1.15):** a library spawns a
   `multiprocessing` child which re-execs the frozen binary as
   `CoCreate -B -S -I -c "from multiprocessing.<x> import main;main(fd)"`.
   The PyInstaller bootloader ignores `-c` and runs `entry.py` → each child wrote
   the PID lockfile, opened a window, spawned more children. `multiprocessing.freeze_support()`
   is a **no-op on POSIX** (Windows-only). Real fix in `entry.py __main__`: detect the
   `-c` argv payload starting `from multiprocessing.` and `exec()` it — the helper does
   its job and exits. Also in place: `argv_emulation=False`, `LSMultipleInstancesProhibited`,
   PID lockfile `~/.cocreate/cocreate.lock` with defer-to-running behavior, and
   `window.events.closed → os._exit(0)` (closing the window must kill the app+server).
2. **macos-14 runner retired** → release jobs cancelled ~2s after queuing. Use `macos-15`.
3. **WKWebView fetch() can't read `Content-Disposition`** — all native saves pass an
   explicit fallback filename to `_SaveApi.save_file` (writes to ~/Downloads, dedups `-N`).
4. **Export 500s:** `notes_to_midi` threw `ValueError data byte must be in range 0..127`
   on out-of-range pitch/vel/instr (AI drafts can emit them). Now clamped; `instr` is
   masked `& 0x7F` (128 = drum sentinel). Symptoms were a file literally containing
   the text `Internal Server Error` saved with no extension.
5. **Loop button dead code:** `AudioEngine.playhead()` returns `endSec` (a number) at
   natural end, never `null` — the loop-restart branch waiting for `null` never ran.
   `tickPlayhead` now detects `t >= endSec` instead.
6. **Session state shape:** `state.session` holds the dict (`.id`, `.name`, `.snapshots`);
   `state.name`/`state.id` do NOT exist.
7. **Boot takes ~10–60s** (torch/transformers import). Window opens instantly on a dark
   "starting up…" page; the server loads in a worker thread (`webview.start(func, args)`)
   and swaps the URL when ready. Never move the heavy imports back to the main thread.
8. **Unsigned installer:** Gatekeeper blocks the downloaded .pkg; `sudo installer -pkg`
    installs anyway (pkg-installed apps don't inherit quarantine). Signing is pending.

## Pending work

- **Developer ID signing + notarization** — user approved doing it "once it tests ok"
  (it now does). Needs from the user: .p12 Developer ID certs, app-specific password,
  Apple ID, Team ID. Then wire signing/notarization into `build_macos.sh` + release.yml.

## Current state

- Live release: **v0.1.16** (only release, `CoCreate-installer.pkg`).
- v0.1.15 confirmed stable by user: no reopen loop, opens once, closes cleanly.
- Feature-complete list: draggable scrub bar, loop button, redo, "Saved versions"
  panel, scrub reset on new session, working Export .mid / Study log / version-mid
  downloads into ~/Downloads.
