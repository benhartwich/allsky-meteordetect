# Changelog

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
