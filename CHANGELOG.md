# Changelog

## Unreleased

- **New `tools/align_overlay.py`: aligns the Allsky Website's constellation overlay** from
  the fisheye calibration instead of by trial and error. Computes `projection`,
  `overlayWidth`/`overlayHeight`, `overlayOffsetLeft`/`overlayOffsetTop` and `az`; picks
  the best of virtualsky's zenith-centred projections by least squares over the visible
  sky and reports the remaining error; `--preview` marks stars vs. overlay on a frame;
  `--apply` writes the values with a backup. Here: `polar`, 1.7° RMS (default `fisheye`
  would be 2.0°). Checked against the real `virtualsky.js` in headless Chromium: 0.00 px
  difference from the tool's model, 1.7° mean from the real stars.

## v0.5.7

- **New edge-glow veto** (`edge_filter`, shadow mode by default). Rejects a long, fat
  streak whose *both* ends sit on the mask border: horizon or lens-rim glow leaking
  through the feathered edge. About a quarter of the detections saved here touched the
  border. The real streaks among them cross it — one end inside — and are thin
  (elongation 10–47); the glow bands lie along it and are fat (5–8).
- Rule: length ≥ 80 px, elongation < 10, both ends within 50 px of the border. Over two
  months it matched **9 detections, all inspected, all edge glow, no real streak**, and
  the result is stable across 50–60 px and 70–80 px. Replaying 2026-09-20 with it
  switched on removes exactly that night's one edge-glow detection and nothing else.
- Every saved meteor now records `edge_d`, the distance of its farther end from the
  border, so you can check your own record before arming it. New settings: Edge Margin,
  Edge Glow Max Elongation, Edge Glow Min Length.

## v0.5.6

- **Fragment Segments (`frag_min`) now defaults to 5, not 3.** The fragmented-trail veto
  has run in shadow mode here for two months, recording `frag_n` for every saved
  detection. Of 107, eleven reached the old threshold of 3. Inspected by eye: seven were
  satellite trails or artefacts, one was unclear — and **three were real meteors**,
  scoring 3, 4 and 3. The assumption that a real meteor scores 0 does not hold. At 5 the
  veto catches the two clearest satellite trails (6 and 11) and no real meteor.
- The veto is still **off** by default; this only makes turning it on safe. README has a
  new section with the numbers and a one-liner to check your own record first.

## v0.5.5

- **Streak finding is about 240× faster.** For every connected component in the
  difference image it ran `np.where(labels == i)` over the *whole* 8-megapixel label
  image. A noisy, moonlit or twinkling sky produces around 1400 components, so a single
  frame could take 60–70 s on a Pi 4 — holding up every module after this one in the
  flow. It now searches only each component's bounding box, which
  `connectedComponentsWithStats` already provides. Same pixels, same order, so the
  results are **identical**: checked on four real frame pairs from 2026-09-17, one of
  them the frame of a live meteor. Time per frame dropped from ~66 s to ~0.27 s.
- Found with the new replay tool, on its first run.
- **New `tools/replay_night.py` — a test mode.** Runs the installed module, with the
  night flow's settings, over a night Allsky already saved, inside a sandbox, and reports
  what it would have confirmed and rejected. `--compare` sets the result against what the
  module saved live that night; `--set key=value` tries a setting without changing it.
  Answers the recurring "is there a way to run a test?" (AllskyTeam/allsky discussion
  #4281) without waiting for a clear night. On 2026-09-17 it found 4 of the 6 live
  meteors, plus two satellite trails and a cloud wisp that live correctly skipped: it
  replays the saved images, which carry the overlay and a second JPEG compression.

## v0.5.4

- **Results are now real Allsky variables.** `AS_METEORCOUNT`, `AS_METEORIMAGE`,
  `AS_METEORIMAGEPATH`, `AS_METEORIMAGEURL`, `AS_METEORMOVING` and `AS_METEORVETOED` are
  declared in `metaData["extradata"]` and written with `saveExtraData`, so they show up in
  the WebUI's variable list and reach MQTT. Until now they were only environment
  variables, which the overlay of the same frame can read but nothing else on Allsky 2025
  can. Reported on [#2](https://github.com/benhartwich/allsky-meteordetect/issues/2) by a
  user feeding Home Assistant from the built-in module's variables.
- **The first four keep the built-in module's names**, so an overlay or MQTT consumer built
  on them keeps working after switching. The image values point at the meteor *saved* on
  the frame rather than the analysed frame, since a meteor is only confirmed one frame
  later.
- Handles both `saveExtraData` signatures: Allsky 2025's
  `(file, data, source, structure, …)` and 2024's `(file, data)`.

## v0.5.3

- **Display name is now “Meteor Detection (temporal)”.** Allsky's built-in
  `allsky_meteor.py` is also called “Meteor Detection”, so the Module Manager listed two
  identical entries — a user on
  [#2](https://github.com/benhartwich/allsky-meteordetect/issues/2) could not tell which
  one they had installed. The README's installation steps now name both.

## v0.5.2

- **WebUI thumbnail folder is now `images/<day>/meteorsthumbnails/`** — plural, like
  the day's own `thumbnails/`, as settled on
  [AllskyTeam/allsky#5227](https://github.com/AllskyTeam/allsky/pull/5227). The WebUI's
  `meteors.php` and `functions.php` read that name; v0.5.1's `meteorsthumbnail/` had
  followed the singular `keogramthumbnail/` pattern instead.
- **`tools/backfill_webui.py` moves thumbnails from both earlier locations**,
  `meteors/thumbnails/` (v0.5.0) and `meteorsthumbnail/` (v0.5.1). Re-run it once after
  upgrading.

## v0.5.1

- **WebUI thumbnails move to `images/<day>/meteorsthumbnail/`**, a sibling of
  `meteors/` rather than a `meteors/thumbnails/` subfolder. Allsky 2025 stores a
  day's keogram and startrails thumbnails the same way (`keogramthumbnail/`,
  `startrailsthumbnail/`), and the WebUI's Meteors page looks for them there —
  requested on [AllskyTeam/allsky#5227](https://github.com/AllskyTeam/allsky/pull/5227).
  The website `meteors/thumbnails/` folder is unchanged: the website gallery and
  the remote upload read that one.
- **`tools/backfill_webui.py` migrates.** It writes thumbnails to the new folder and
  moves any a v0.5.0 install left in `images/<day>/meteors/thumbnails/`, removing
  the emptied folder. Re-run it once after upgrading.

## v0.5.0

Make the detections browsable in the **Allsky WebUI**, alongside the existing website
gallery (see [AllskyTeam/allsky#5227](https://github.com/AllskyTeam/allsky/pull/5227)).

- **WebUI meteor browsing** (`save_webui`, default on). Every saved meteor is now
  additionally filed under `images/<day>/meteors/` — image, thumbnail, marked copy
  and a json sidecar — which is the layout the WebUI's *Meteors* page browses. The
  website `meteors/` folder is written exactly as before, so the remote upload and
  the per-night charts keep reading the rolling `meteors.json` there. Nothing moves;
  the WebUI copy is an addition.
- **Per-image json sidecar** `meteors-<timestamp>.json` next to each image, holding
  just that image's streaks. Same fields as the rolling log (`length`, `angle`,
  `elong`, `peak`, `p1`, `p2`, `frag_n`, `frag_ext`, `showers`, `radiant`) — the
  WebUI reads metadata one file per image rather than scanning a rolling log.
- **Marked copy promoted out of Debug** (`save_marked`, default **on**) and its
  thumbnail is now written too. The WebUI's *Use Marked Meteors* option links
  `thumbnails/<name>-marked.jpg` without checking that it exists, so a missing
  thumbnail renders as a broken image. `save_debug` stays as a legacy alias: an
  existing config that had it on still forces the marked copy on.
- **Day folder pinned at stash time.** A candidate is only confirmed on a later
  frame, which may already sit in the next `DATE_NAME` period; the night's folder is
  now recorded when the candidate is stashed, so a meteor caught either side of the
  rollover cannot land in the wrong night.

## v0.4.4

Reject **bright-star scintillation** — the clear-night false positive geometry alone
can't rule out.

- **Bright-star scintillation veto** (`star_filter`, default on). On a clear night a
  bright star twinkles brighter between two frames, so the frame difference shows a
  short compact blob *at the star's position* — the appear/vanish signature of a
  meteor. The module now projects a bundled Hipparcos subset (`stars.json`,
  Vmag < 6) with the fisheye calibration for the frame's time and rejects a short
  candidate landing within `star_radius` px (default 16) of a star brighter than
  `star_maglim` (default 5.0). Long/bright fireballs (>130 px) are exempt. Logged as
  reason `star` in `meteors_vetoed.json`. Silently skipped without
  `allsky_fisheye.py` / `calibration.json` / `stars.json`.
  - Validated against local history: **0 of 24** confirmed short meteors would be
    caught (no real meteor harmed), while genuine bright-star scintillation blobs are
    rejected precisely.
- **Refined fisheye calibration.** Re-fit against a deep Hipparcos catalogue, seeded
  from the previous solution, over three clear-night frames (RMS ~4 px, 317 stars).
  The old `a1` had pushed mid/edge stars ~15 px outward — enough to blunt a
  position-based star veto — so this tightening is a prerequisite for the veto above.

## v0.4.3

Groundwork for a learned classifier: capture the **negative** examples.

- **Rejected-candidate crops** (`save_vetoed`, default on). Every vetoed streak —
  the recurrence / star-trail / dashed / fragmented rejects **and** the
  satellites/aircraft caught by the moving-track filter — is now saved as a small
  crop in a `vetoed/` subfolder and recorded (a `thumb` field) in
  `meteors_vetoed.json`, then uploaded to the remote `meteors/vetoed/` folder.
  These are the negatives; labelling them on the website (aircraft / satellite /
  artifact / meteor / unsure) builds a training set. The confirmed meteors are the
  positives. A companion `tools/train_classifier.py` reads both plus the human
  `labels.json`.
- The remote `meteors/vetoed/` folder must exist first — `upload.sh` does not
  create directories (create it once over SFTP).

## v0.4.2

Fixes a remote-upload bug that froze the online gallery on a single night.

- **Remote `meteors.json` upload fix.** The per-hit upload loop uploads three
  files — the meteor image, its thumbnail and the `meteors.json` index — but
  passed the *image's* filename as the remote destination name for **all three**.
  So the index was uploaded to the remote website under the image's name, and the
  real remote `meteors.json` was never refreshed: the online gallery and the
  per-night chart stayed frozen on the first night ever detected, even though new
  images kept arriving. Each file now keeps its own remote name. (The local
  `meteors.json` and the image/thumbnail uploads were always correct — only the
  remote index name was wrong.)

## v0.4.1

Closes the fragmented-trail gap the v0.4.0 "Known limitation" called out —
shipped in **shadow mode** so it gathers evidence before it is trusted to veto.

- **Fragmented-trail metric** (`frag_filter`, **off / shadow by default**). The
  v0.4.0 dash veto samples only a streak's *continuous* head, so a satellite
  glint whose dashed tail is broken into separate sub-threshold pieces slips
  through as a lone bright head (exactly what happened on 2026-07-13: a 154-px
  head scored 1 dash-run and was saved as a "meteor"). The new metric counts
  difference-image components lying **collinear** — within a few pixels of the
  streak's axis line — *beyond* its endpoints. A real meteor has nothing
  collinear past its ends (score 0); the validated glint scored 3. It is
  measured on the **difference** image, where static stars cancel, so a star
  near the axis is never miscounted as a fragment.
- **Shadow mode.** With `frag_filter` off, the metric is only *logged* — a
  `frag-shadow` entry in `meteors_vetoed.json` for anything it would reject, and
  `frag_n` / `frag_ext` on every saved meteor in `meteors.json` — but nothing is
  vetoed. Arm it (`frag_filter` on, `frag_min` = 3) only once real meteors have
  confirmed they score 0, so a genuine meteor is never lost to an unproven
  filter. `frag_min_len` (120 px) exempts short streaks.

## v0.4.0

A dashed-trail veto and tighter shape floors, tuned against a real clear night
(2026-07-13) whose six detections were one real meteor, one satellite, and four
edge/compact false positives.

- **Dashed-trail veto** (`dash_filter`, default on): reject a long streak broken
  into many bright/dark segments along its axis — a tumbling satellite or a
  strobing aircraft. Intensity is sampled along the streak's principal axis and
  the separate bright runs are counted; a real meteor scores ≤5, the night's
  dashed satellite scored 19. Only streaks at least `dash_min_len` (120 px) are
  tested, so a short genuine meteor is never dash-vetoed. `dash_runs` (default 10)
  is the segment count that marks a trail as dashed.
- **Tighter shape floors**: default min elongation 4.0 → 5.0 and min length
  40 → 50. The real meteors measured elongation 7–8, while the compact false
  positives were barely-elongated (~4) blobs — defocused stars near the fisheye
  edge — sitting right on the old floors.
- Validated end-to-end against the night's detections: the real meteor kept, the
  satellite and both compact blobs vetoed (5/5 unambiguous cases correct).

### Known limitation

A plane or satellite that crosses within a single exposure is *temporally*
identical to a meteor — it appears then disappears at one spot — so only its
shape betrays it. If such a trail is fragmented (by the mask or the frame edge)
into a single short piece, that piece can still pass the shape filters. On the
same night a long aircraft trail was logged as one 80-px edge fragment and
slipped through. Reassembling collinear fragments before the veto is the next
step.

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
