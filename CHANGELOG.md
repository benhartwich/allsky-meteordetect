# Changelog

## v0.3.0

Two false-positive vetoes aimed at clear-night artifacts, plus geometry logging
for validation. Motivated by a clear Milky-Way night where ~30 of 37 "meteors"
were star scintillation/bloom and a handful were satellites, with only ~1 real.

- **Recurrence veto** (`repeat_filter`, default on): reject a streak whose position
  keeps producing detections across several frames — scintillation, bloom, a
  trailed star, a fixed reflection. Tracked in a rolling ~25-min / ~55-px hot-spot
  memory. A real meteor appears exactly once, so it can never accumulate and is
  never vetoed by this. `repeat_k` (default 3) sets how many earlier frames at the
  same spot count as recurring.
- **Star-trail veto** (`trail_filter`, default on): reject a streak whose
  orientation matches the local diurnal star-trail tangent, computed from the
  fisheye calibration (rotate the sky vector about the celestial pole → tangent).
  Long/bright fireballs (>130 px) are exempt so a real bolide parallel to the
  trails is never lost. `trail_tol` (default 12°). Silently skipped without
  `allsky_fisheye.py` / `calibration.json`.
- Confirmed meteors now log their streak geometry (`cx,cy,p1,p2`), and every
  rejected streak is appended to a rolling `meteors_vetoed.json` with its reason —
  so the filters can be checked against a real night before being trusted.
- New env var `AS_METEORVETOED`.

## v0.2.1

- Fix: also upload `meteors.json` to the remote website, not just the images and
  thumbnails. Without the index file the remote gallery and the per-night chart
  had the pictures but no data, so both stayed empty. The log now rides along on
  every confirmed hit (remote dir `<remotewebsiteimagedir>/meteors`).

## v0.1.0

Initial release.

- Temporal meteor detector: frame differencing → masked → connected-components +
  PCA streaks → neighbour-frame classification.
- Deferred confirmation (one frame) so satellites/aircraft are rejected even on
  their first appearance.
- Cloud gate, twilight gate and soft (feathered) mask edge to suppress false
  positives.
- Gallery image is saved in true colour, untouched; an optional marked copy
  draws brackets *around* the streak, never over it, so meteor colour is kept.
- Writes `meteors-<timestamp>.jpg` + thumbnail into the Allsky website `meteors`
  folder and appends to `meteors.json`.
- Optional upload of each hit to the remote website via Allsky's `upload.sh`.
- `tools/build_mask.py` builds a detection mask from daytime images using a
  dark-frequency method that cleanly separates trees/horizon from sky.

## v0.1.1

- Add same-location appear/disappear confirmation: a candidate is only kept if the
  next frame repeats it at the same spot, rejecting random flicker.
- Raise default Min Streak Length 25→40 and Min Elongation 3.0→4.0 — the main lever
  against short star-scintillation artifacts on clear nights.
- Scintillation guard for dense clear-night frames.
- Document that clear nights are the hard case and geometry is the primary defense.

## v0.2.0

- Record meteor peak brightness (peak new-light intensity) per detection.
- Date-based meteor-shower context: each detection is tagged with the showers
  active on that date (Perseids, Geminids, …) or flagged sporadic.
- **Geometric radiant matching** (optional): `tools/calibrate_fisheye.py` fits the
  fisheye projection from a plate-solved night frame (astrometry.net-bootstrapped;
  verified to 0.11° RMS over 228 stars), `allsky_fisheye.py` provides
  pixel↔alt/az + `match_radiant`, and each meteor is attributed to the shower whose
  radiant lies on its great circle. Silently skipped if `allsky_fisheye.py` /
  `calibration.json` are absent. The calibration is per-camera.
