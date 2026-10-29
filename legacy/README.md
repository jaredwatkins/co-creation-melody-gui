# Legacy Magenta scripts

`generate.py` and `generate_cat_mel.py` are early experiments built on
[Magenta](https://github.com/magenta/magenta) (MusicVAE / PerformanceRNN) and
`note_seq`. They are kept for provenance only and are **not** part of the
supported pipeline:

- They require `tensorflow==1.15` + `magenta==1.1.7`, which only run on
  Python 3.7 and are effectively uninstallable on a modern machine.
- The `.mag` / `.tar` checkpoint files previously committed here were
  ~200-byte Google Cloud Storage error pages saved by a failed download —
  not real model bundles — so the scripts could never run as committed.
  Genuine bundles can be fetched from
  https://github.com/magenta/magenta/tree/main/magenta/models (e.g.
  `performance_with_dynamics.mag` under Performance RNN).

The working, supported model path is the Stanford Anticipatory Music
Transformer in `/anticipation`, driven by `run_anticipation.py` or the
`cocreate` web app.
