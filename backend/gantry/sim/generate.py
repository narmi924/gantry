"""Generate the demo match.

Plays seeds in parallel until one follows the script: Kingsmere score in the
first half, Ashvale equalise after their substitutions, Kingsmere win it in
stoppage time.

    uv run python -m gantry.sim.generate --id demo
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed

from .engine import Engine
from .report import summarize
from .store import save


def play(seed: int):
    e = Engine(seed=seed).run()
    missed = e.director.missed_beats(1e9)
    goals = [x for x in e.events if x["type"] == "goal"]
    # the "follow my player" feed follows Kingsmere's number 10, so he should be part of a goal
    star = any("KSM-10" in (x.get("player"), x.get("assist")) for x in goals)
    corners = sum(1 for x in e.events if x["type"] == "corner")
    shots = [sum(1 for x in e.events if x["type"] == "shot" and x["team"] == t) for t in (0, 1)]
    believable = shots[0] <= 28 and shots[1] >= 6
    ok = not missed and e.score == [2, 1] and star and corners >= 6 and believable
    return seed, ok, e if ok else None, f"score {e.score} missed {missed} shots {shots} corners {corners} star {star}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="demo")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--tries", type=int, default=32)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=None, help="play this seed directly instead of searching")
    args = ap.parse_args()

    if args.seed is not None:
        engine = Engine(seed=args.seed).run()
        path = save(engine, args.id)
        print(f"Saved seed {args.seed} to {path}: {engine.score}")
        return

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(play, s) for s in range(args.start, args.start + args.tries)]
        best = None
        for fut in as_completed(futures):
            seed, ok, engine, note = fut.result()
            print(f"seed {seed}: {'follows the script' if ok else 'no'} ({note})", flush=True)
            if ok and (best is None or seed < best.seed):
                best = engine
        if best is None:
            raise SystemExit("No seed followed the script; try more seeds.")

    path = save(best, args.id)
    report = summarize(best)
    print(f"\nSaved seed {best.seed} to {path}")
    for k in ("score", "minutes", "in_play", "goals", "team0", "team1"):
        print(k, report[k])


if __name__ == "__main__":
    main()
