"""Terminal runner for the Stanford Anticipatory Music Transformer.

Generates a free-running continuation (or, with --input, a continuation of an
existing MIDI file) and writes a .mid file — plus a .wav when FluidSynth and a
SoundFont are available.

    python run_anticipation.py --seconds 10 --output output.mid
    python run_anticipation.py --input seed.mid --start 8 --seconds 8
"""

import argparse
import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEFAULT_MODEL = "stanford-crfm/music-small-800k"
DEFAULT_SOUNDFONTS = [
    os.environ.get("SOUNDFONT", ""),
    "/Library/Audio/Sounds/Banks/FluidR3_GM.sf2",  # macOS default
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",        # Debian/Ubuntu
    "/usr/share/soundfonts/FluidR3_GM.sf2",        # Fedora
]


def pick_device(requested):
    if requested != "auto":
        return requested
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", help="optional seed MIDI file to continue")
    parser.add_argument("--output", default="output.mid", help="output .mid path")
    parser.add_argument("--start", type=float, default=None,
                        help="time (seconds) to start generating from; defaults to end of the seed")
    parser.add_argument("--seconds", type=float, default=10.0,
                        help="how many seconds of music to generate")
    parser.add_argument("--top-p", type=float, default=0.98, help="nucleus sampling threshold")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="HuggingFace model id or local path")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "mps"])
    parser.add_argument("--audio", action="store_true",
                        help="also synthesize a .wav via FluidSynth (needs fluidsynth + a SoundFont)")
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForCausalLM

    from anticipation.convert import events_to_midi, midi_to_events
    from anticipation.sample import generate

    device = pick_device(args.device)
    print(f"Loading {args.model} on {device}...")
    model = AutoModelForCausalLM.from_pretrained(args.model).to(device)

    inputs = None
    start = 0.0
    if args.input:
        inputs = midi_to_events(args.input)
        from anticipation import ops
        start = args.start if args.start is not None else ops.max_time(inputs)
        print(f"Seeded from {args.input} ({len(inputs)//3} events), continuing at {start:.1f}s")

    print(f"Generating {args.seconds}s of music (top_p={args.top_p})...")
    tokens = generate(model, start_time=start, end_time=start + args.seconds,
                      inputs=inputs, top_p=args.top_p)

    mid = events_to_midi(tokens)
    mid.save(args.output)
    print(f"Wrote {args.output}")

    if args.audio:
        wav = os.path.splitext(args.output)[0] + ".wav"
        soundfont = next((p for p in DEFAULT_SOUNDFONTS if p and os.path.exists(p)), None)
        if soundfont is None or shutil.which("fluidsynth") is None:
            print("FluidSynth or a SoundFont not found; skipped audio synthesis.")
        else:
            from midi2audio import FluidSynth
            FluidSynth(soundfont).midi_to_audio(args.output, wav)
            print(f"Wrote {wav}")


if __name__ == "__main__":
    main()
