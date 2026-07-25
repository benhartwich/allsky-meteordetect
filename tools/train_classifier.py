#!/usr/bin/env python3
"""
train_classifier.py — learn "meteor vs. not-a-meteor" from the detector's own log.

The temporal detector already writes everything a classifier needs:

  * meteors.json         — the confirmed detections  (candidate POSITIVES)
  * meteors_vetoed.json  — the rejected streaks       (NEGATIVES, with a reason)
  * labels.json          — human classifications from the website  (ground truth)

Each detection carries geometric features (length, elongation, peak brightness,
orientation). This script assembles them into a labelled table — human labels win,
otherwise a weak label is inferred from the source (a confirmed meteor → "meteor";
a vetoed streak → its reason maps to aircraft / satellite / artifact) — and trains a
small logistic-regression classifier (pure NumPy, no scikit-learn needed) with
standardisation and stratified k-fold cross-validation.

It is deliberately runnable *now*, on the weak labels alone, as a baseline; every
human label added on the website makes it sharper. The learned model is written to
classifier.json (weights + standardisation) so the module could later score live
candidates.

Usage:
    python3 train_classifier.py [--dir <meteors folder>] [--labels <labels.json>]
                                [--report] [--min-human N]

Defaults assume the standard Allsky layout (~/allsky/html/allsky/meteors and
../labels.json). Copy the remote labels.json down first if you annotate online:
    curl -s https://<site>/label.php -o ~/allsky/html/allsky/labels.json
"""
import argparse
import json
import os
import sys

import numpy as np

# Map a veto reason (or a human label) to a coarse physical class. Everything that
# is not a genuine meteor is a negative for the binary task.
REASON_TO_CLASS = {
    "moving": "satellite_or_aircraft",
    "dashed": "satellite_or_aircraft",
    "trail": "star_trail",
    "repeat": "artifact",
    "fragmented": "satellite_or_aircraft",
    "frag-shadow": "meteor",   # shadow-mode only logs it; the streak was KEPT as a meteor
}
HUMAN_TO_BINARY = {
    "meteor": 1, "aircraft": 0, "satellite": 0, "artifact": 0,
    # "unsure" -> dropped
}
FEATURES = ["length", "elong", "peak", "abs_ang"]


def _num(v, default=np.nan):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _feat(row):
    """Feature vector, tolerant of the two schemas (meteors.json vs vetoed)."""
    length = _num(row.get("length", row.get("len")))
    elong = _num(row.get("elong"))
    peak = _num(row.get("peak"))
    ang = _num(row.get("angle", row.get("ang")), 0.0)
    abs_ang = abs(((ang + 90.0) % 180.0) - 90.0)   # fold to 0..90, orientation only
    return [length, elong, peak, abs_ang]


def load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as ex:
        print(f"  ! could not read {path}: {ex}", file=sys.stderr)
        return None


def assemble(meteors, vetoed, labels):
    """Return (X, y, meta) for the binary meteor(1)/not(0) task. Human labels win."""
    rows = []
    for m in meteors or []:
        rows.append((m.get("file"), m, "meteor"))                 # weak positive
    for v in vetoed or []:
        wk = REASON_TO_CLASS.get(v.get("reason"), "artifact")
        rows.append((v.get("thumb"), v, "meteor" if wk == "meteor" else "neg"))

    X, y, src = [], [], {"human": 0, "weak": 0, "dropped_unsure": 0, "dropped_nan": 0}
    for ident, row, weak in rows:
        human = (labels.get(ident) or {}).get("label") if ident else None
        if human is not None:
            if human == "unsure":
                src["dropped_unsure"] += 1
                continue
            label = HUMAN_TO_BINARY.get(human)
            if label is None:
                continue
            src["human"] += 1
        else:
            label = 1 if weak == "meteor" else 0
            src["weak"] += 1
        f = _feat(row)
        if any(np.isnan(f)):
            src["dropped_nan"] += 1
            continue
        X.append(f)
        y.append(label)
    return np.array(X, float), np.array(y, int), src


def standardise(X):
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0] = 1.0
    return (X - mean) / std, mean, std


def fit_logreg(X, y, l2=1.0, iters=4000, lr=0.1):
    """Plain L2-regularised logistic regression via gradient descent (NumPy only)."""
    n, d = X.shape
    Xb = np.hstack([X, np.ones((n, 1))])          # bias column
    w = np.zeros(d + 1)
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-Xb @ w))
        grad = Xb.T @ (p - y) / n
        grad[:-1] += (l2 / n) * w[:-1]            # don't regularise bias
        w -= lr * grad
    return w


def predict(w, X):
    Xb = np.hstack([X, np.ones((X.shape[0], 1))])
    return 1.0 / (1.0 + np.exp(-Xb @ w))


def stratified_folds(y, k, seed=0):
    rng = np.random.default_rng(seed)
    folds = [[] for _ in range(k)]
    for cls in np.unique(y):
        idx = np.where(y == cls)[0]
        rng.shuffle(idx)
        for i, j in enumerate(idx):
            folds[i % k].append(j)
    return [np.array(sorted(f)) for f in folds]


def cross_val(X, y, k=5):
    if len(y) < 2 * k or len(np.unique(y)) < 2:
        return None
    folds = stratified_folds(y, k)
    acc, prec, rec = [], [], []
    for i in range(k):
        te = folds[i]
        tr = np.concatenate([folds[j] for j in range(k) if j != i])
        if len(np.unique(y[tr])) < 2:
            continue
        Xtr, mean, std = standardise(X[tr])
        w = fit_logreg(Xtr, y[tr])
        pred = (predict(w, (X[te] - mean) / std) >= 0.5).astype(int)
        tp = int(((pred == 1) & (y[te] == 1)).sum())
        fp = int(((pred == 1) & (y[te] == 0)).sum())
        fn = int(((pred == 0) & (y[te] == 1)).sum())
        acc.append(float((pred == y[te]).mean()))
        prec.append(tp / (tp + fp) if tp + fp else float("nan"))
        rec.append(tp / (tp + fn) if tp + fn else float("nan"))
    return {"accuracy": np.nanmean(acc), "precision": np.nanmean(prec),
            "recall": np.nanmean(rec), "folds": len(acc)}


def report_distributions(X, y):
    print("\nFeature distribution by class (median [min..max]):")
    for ci, name in [(1, "meteor"), (0, "not-meteor")]:
        sub = X[y == ci]
        if not len(sub):
            print(f"  {name:11}: (none)")
            continue
        parts = [f"{FEATURES[j]}={np.median(sub[:, j]):.1f}"
                 f"[{sub[:, j].min():.0f}..{sub[:, j].max():.0f}]" for j in range(X.shape[1])]
        print(f"  {name:11} (n={len(sub):3}): " + "  ".join(parts))


def main():
    ap = argparse.ArgumentParser(description="Train a meteor vs. not-meteor classifier from the detector logs.")
    home = os.environ.get("ALLSKY_HOME", os.path.expanduser("~/allsky"))
    ap.add_argument("--dir", default=os.path.join(home, "html", "allsky", "meteors"),
                    help="folder holding meteors.json + meteors_vetoed.json")
    ap.add_argument("--labels", default=None, help="labels.json (default: <dir>/../labels.json)")
    ap.add_argument("--out", default=None, help="where to write classifier.json (default: <dir>/classifier.json)")
    ap.add_argument("--min-human", type=int, default=40,
                    help="human labels below which this is only a weak-label baseline (default 40)")
    ap.add_argument("--report", action="store_true", help="print feature distributions and exit (no training)")
    args = ap.parse_args()

    labels_path = args.labels or os.path.join(args.dir, "..", "labels.json")
    out_path = args.out or os.path.join(args.dir, "classifier.json")

    meteors = load(os.path.join(args.dir, "meteors.json")) or []
    vetoed = load(os.path.join(args.dir, "meteors_vetoed.json")) or []
    labels = load(labels_path) or {}
    if isinstance(labels, list):     # empty label store serialises as []
        labels = {}

    print(f"Sources:  meteors={len(meteors)}  vetoed={len(vetoed)}  human-labels={len(labels)}")
    X, y, src = assemble(meteors, vetoed, labels)
    print(f"Dataset:  {len(y)} samples  ({int((y == 1).sum())} meteor / {int((y == 0).sum())} not)")
    print(f"          labels used: {src['human']} human, {src['weak']} weak; "
          f"dropped {src['dropped_unsure']} unsure, {src['dropped_nan']} missing-features")

    if len(y) < 8 or len(np.unique(y)) < 2:
        print("\nNot enough labelled data yet to train — need both classes and >=8 samples.")
        if len(y):
            report_distributions(X, y)
        return

    report_distributions(X, y)

    if src["human"] < args.min_human:
        print(f"\n⚠  Only {src['human']} human labels (< {args.min_human}). Treat the model below as a "
              f"WEAK-LABEL BASELINE — it partly learns the detector's own heuristics. "
              f"Label more on the website (especially the vetoed candidates) to make it real.")

    cv = cross_val(X, y)
    if cv:
        print(f"\n{cv['folds']}-fold CV:  accuracy {cv['accuracy']*100:.1f}%  "
              f"precision {cv['precision']*100:.1f}%  recall {cv['recall']*100:.1f}%")

    Xs, mean, std = standardise(X)
    w = fit_logreg(Xs, y)
    print("\nLearned weights (standardised; sign shows push toward 'meteor'):")
    for name, wi in sorted(zip(FEATURES, w[:-1]), key=lambda t: -abs(t[1])):
        print(f"  {name:9} {wi:+.3f}")

    model = {"type": "logreg", "features": FEATURES,
             "mean": mean.tolist(), "std": std.tolist(), "weights": w.tolist(),
             "n_samples": int(len(y)), "n_human": int(src["human"]),
             "cv": cv}
    try:
        with open(out_path, "w") as fh:
            json.dump(model, fh, indent=2)
        print(f"\nModel written to {out_path}")
    except Exception as ex:
        print(f"\n! could not write model: {ex}", file=sys.stderr)


if __name__ == "__main__":
    main()
