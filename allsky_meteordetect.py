""" allsky_meteordetect.py

Temporal meteor detection module for Allsky.
https://github.com/AllskyTeam/allsky

Unlike the built-in single-frame detector, this module works on the DIFFERENCE
between consecutive frames (removes stars / static clouds), finds streaks via
connected-components + PCA, and classifies them across neighbouring frames:

    * a streak that continues a PROGRESSING track   -> satellite / aircraft (rejected)
    * a streak that repeats at the SAME location     -> disappearance of an already
                                                        reported meteor (de-duplicated)
    * an isolated, transient streak                  -> meteor candidate (saved)

The saved gallery image keeps the TRUE COLOURS of the meteor untouched; the optional
debug image draws brackets AROUND the streak, never over it, so the meteor's colour
(green = Mg/O, yellow = Na/Fe, ...) is preserved.
"""
import allsky_shared as s
import os
import json
import time
import subprocess
import cv2
import numpy as np

metaData = {
    "name": "Meteor Detection",
    "description": "Detects meteors via frame differencing and separates them from satellites/aircraft",
    "version": "v0.4.1",
    "events": [
        "night"
    ],
    "experimental": "false",
    "module": "allsky_meteordetect",
    "arguments": {
        "mask": "meteor_mask.png",
        "min_length": "50",
        "diff_thr": "22",
        "min_elong": "5.0",
        "max_area": "6000",
        "cloud_frac": "2.0",
        "edge_feather": "35",
        "dash_filter": "true",
        "dash_runs": "10",
        "dash_min_len": "120",
        "frag_filter": "false",
        "frag_min": "3",
        "frag_min_len": "120",
        "satellite_filter": "true",
        "scint_guard": "true",
        "scint_max": "8",
        "repeat_filter": "true",
        "repeat_k": "3",
        "trail_filter": "true",
        "trail_tol": "12",
        "upload_remote": "true",
        "outputdir": "",
        "save_debug": "false",
        "debug": "false"
    },
    "argumentdetails": {
        "mask": {
            "required": "false",
            "description": "Detection Mask",
            "help": "Image mask in the overlay images folder. White = sky to analyse, black = ignore (trees/horizon). Build one with the supplied mask tool.",
            "type": {"fieldtype": "image"}
        },
        "min_length": {
            "required": "true",
            "description": "Min Streak Length (px)",
            "help": "Minimum length of a detected streak in pixels. Short compact blobs near the fisheye edge are defocused stars, not meteors; keep this around 50.",
            "type": {"fieldtype": "spinner", "min": 5, "max": 500, "step": 1}
        },
        "diff_thr": {
            "required": "true",
            "description": "Difference Threshold",
            "help": "Brightness increase over the previous frame for a pixel to count as 'new'. Higher = fewer, brighter detections.",
            "type": {"fieldtype": "spinner", "min": 5, "max": 100, "step": 1}
        },
        "min_elong": {
            "required": "false",
            "description": "Min Elongation",
            "help": "Length/width ratio. Low values pass blobs (defocused stars, cloud); high values require a thin streak. Real meteors here measured >=7; barely-elongated (~4) detections are defocused stars, so keep this around 5.",
            "type": {"fieldtype": "spinner", "min": 1.5, "max": 10, "step": 0.5}
        },
        "max_area": {
            "required": "false",
            "description": "Max Streak Area (px)",
            "help": "Larger connected regions are treated as cloud brightening, not meteors",
            "type": {"fieldtype": "spinner", "min": 500, "max": 50000, "step": 100}
        },
        "cloud_frac": {
            "required": "false",
            "description": "Cloud Skip (%)",
            "help": "If more than this percentage of the sky changed since the last frame the frame is skipped as cloudy",
            "type": {"fieldtype": "spinner", "min": 0.2, "max": 20, "step": 0.1}
        },
        "edge_feather": {
            "required": "false",
            "description": "Mask Edge Feather (px)",
            "help": "Soft fade of the mask edge so the mask boundary itself is not detected as a streak",
            "type": {"fieldtype": "spinner", "min": 0, "max": 151, "step": 2}
        },
        "dash_filter": {
            "required": "false",
            "description": "Reject Dashed Trails",
            "help": "Reject a long streak that is broken into many bright/dark segments along its length. A meteor is one continuous streak; a tumbling satellite or a strobing aircraft leaves a dashed trail. Catches a single-frame satellite/aircraft that the cross-frame filter cannot see.",
            "type": {"fieldtype": "checkbox"}
        },
        "dash_runs": {
            "required": "false",
            "description": "Dash Segments",
            "help": "How many separate bright segments along a streak's axis mark it as a dashed (satellite/aircraft) trail. A real meteor scores <=5 here; a dashed satellite scored 19. Keep at 10 for a wide safety margin.",
            "type": {"fieldtype": "spinner", "min": 4, "max": 40, "step": 1}
        },
        "dash_min_len": {
            "required": "false",
            "description": "Dash Min Length (px)",
            "help": "Only test streaks at least this long for a dashed pattern. Short streaks are exempt so a genuine short meteor is never dash-vetoed (satellite/aircraft trails are long).",
            "type": {"fieldtype": "spinner", "min": 40, "max": 500, "step": 10}
        },
        "frag_filter": {
            "required": "false",
            "description": "Reject Fragmented Trails (arm)",
            "help": "Reject a streak that is only the bright head of a longer DASHED trail whose faint segments were split into separate sub-threshold fragments (a satellite glint the dash veto misses because it measures only the continuous head). Counts diff components lying collinear beyond the streak's ends. OFF by default = shadow mode: the metric is measured and logged (frag-shadow in meteors_vetoed.json, frag_n on each saved meteor) but nothing is vetoed. Turn ON only after real meteors have confirmed they score 0.",
            "type": {"fieldtype": "checkbox"}
        },
        "frag_min": {
            "required": "false",
            "description": "Fragment Segments",
            "help": "How many collinear diff fragments beyond a streak's ends mark it as the head of a fragmented dashed trail. A real meteor has nothing collinear beyond it (0); the validated satellite glint scored 3.",
            "type": {"fieldtype": "spinner", "min": 2, "max": 20, "step": 1}
        },
        "frag_min_len": {
            "required": "false",
            "description": "Fragment Min Length (px)",
            "help": "Only test streaks at least this long for a collinear fragmented tail. Short streaks are exempt.",
            "type": {"fieldtype": "spinner", "min": 40, "max": 500, "step": 10}
        },
        "satellite_filter": {
            "required": "false",
            "description": "Reject Satellites/Aircraft",
            "help": "Discard streaks that continue a moving track across consecutive frames",
            "type": {"fieldtype": "checkbox"}
        },
        "scint_guard": {
            "required": "false",
            "description": "Scintillation Guard",
            "help": "On very clear nights star twinkling produces many tiny streaks. If a frame has more than 'Scintillation Max' streaks, keep only a clearly dominant one (a real bright meteor) and otherwise skip the frame.",
            "type": {"fieldtype": "checkbox"}
        },
        "scint_max": {
            "required": "false",
            "description": "Scintillation Max",
            "help": "How many streaks in a single frame count as a scintillation-dominated (noisy) frame",
            "type": {"fieldtype": "spinner", "min": 3, "max": 50, "step": 1}
        },
        "repeat_filter": {
            "required": "false",
            "description": "Reject Recurring Positions",
            "help": "Reject a streak whose position keeps producing detections across several frames (scintillation, bloom, a trailed star, a fixed reflection). A real meteor appears once, so it is never caught by this.",
            "type": {"fieldtype": "checkbox"}
        },
        "repeat_k": {
            "required": "false",
            "description": "Recurrence Frames",
            "help": "How many earlier frames must show a detection at the same spot (within ~55 px, last ~25 min) for it to count as a recurring artifact. A meteor gives at most 2, so keep this at 3 or higher.",
            "type": {"fieldtype": "spinner", "min": 2, "max": 10, "step": 1}
        },
        "trail_filter": {
            "required": "false",
            "description": "Reject Star-Trail Orientation",
            "help": "Reject a streak whose orientation matches the local diurnal star-trail direction (computed from the fisheye calibration). Long/bright fireballs are exempt. Needs allsky_fisheye.py + calibration.json; silently skipped otherwise.",
            "type": {"fieldtype": "checkbox"}
        },
        "trail_tol": {
            "required": "false",
            "description": "Star-Trail Tolerance (deg)",
            "help": "How close a streak's angle must be to the local star-trail direction to be rejected. Larger = stricter (rejects more), but risks discarding a real meteor that happens to run parallel to the star trails.",
            "type": {"fieldtype": "spinner", "min": 4, "max": 30, "step": 1}
        },
        "upload_remote": {
            "required": "false",
            "description": "Upload to Remote Website",
            "help": "If the remote website is enabled, upload each meteor image + thumbnail to it (folder 'meteors')",
            "type": {"fieldtype": "checkbox"}
        },
        "outputdir": {
            "required": "false",
            "description": "Output Folder",
            "help": "Where meteor images are written (with a thumbnails/ subfolder). Empty = website meteors folder.",
            "type": {"fieldtype": "text"}
        },
        "save_debug": {
            "required": "false",
            "description": "Save Marked Copy",
            "help": "Additionally save a copy with brackets AROUND the streak (never over it). Gallery image always stays untouched.",
            "tab": "Debug",
            "type": {"fieldtype": "checkbox"}
        },
        "debug": {
            "required": "false",
            "description": "Enable stage debug images",
            "help": "Write intermediate images to the allsky tmp debug folder",
            "tab": "Debug",
            "type": {"fieldtype": "checkbox"}
        }
    },
    "changelog": {
        "v0.1.0": [
            {
                "author": "Benjamin Hartwich",
                "authorurl": "https://astronomy.garden",
                "changes": "Initial temporal detector (frame diff + PCA streaks + neighbour-frame classification)"
            }
        ],
        "v0.2.0": [
            {
                "author": "Benjamin Hartwich",
                "authorurl": "https://astronomy.garden",
                "changes": [
                    "Record meteor peak brightness + date-based active-shower context",
                    "Optional geometric radiant matching via a plate-solved fisheye calibration (allsky_fisheye.py + calibration.json) — attributes each meteor to the shower whose radiant lies on its great circle"
                ]
            }
        ],
        "v0.3.0": [
            {
                "author": "Benjamin Hartwich",
                "authorurl": "https://astronomy.garden",
                "changes": [
                    "Recurrence veto: reject a streak whose position keeps firing across several frames (scintillation / bloom / trailed star / fixed reflection). A real meteor appears once, so it is never affected.",
                    "Star-trail veto: reject a streak whose orientation matches the local diurnal star-trail tangent (from the fisheye calibration); long/bright fireballs are exempt.",
                    "Log streak geometry (centroid + endpoints) with each confirmed meteor, and write a rolling meteors_vetoed.json of rejected streaks + reason for tuning/validation."
                ]
            }
        ],
        "v0.4.0": [
            {
                "author": "Benjamin Hartwich",
                "authorurl": "https://astronomy.garden",
                "changes": [
                    "Dashed-trail veto: reject a long streak broken into many bright/dark segments along its axis (a tumbling satellite / strobing aircraft). Catches a single-frame satellite pass the cross-frame filter cannot see. Tuned on real data — a dashed satellite scored 19 segments, real meteors <=5.",
                    "Raise default min elongation 4.0 -> 5.0 and min length 40 -> 50: barely-elongated short blobs near the fisheye edge are defocused stars, not meteors. Validated against a clear night where the two real meteors measured elongation 7-8 while the false positives sat right on the old 4.0/40 floors."
                ]
            }
        ],
        "v0.4.1": [
            {
                "author": "Benjamin Hartwich",
                "authorurl": "https://astronomy.garden",
                "changes": [
                    "Fragmented-trail metric (frag_filter, SHADOW by default): the v0.4.0 dash veto measures only a streak's continuous head, so a satellite glint whose dashed tail is split into separate sub-threshold fragments slips through as a lone bright head. This counts difference components lying collinear (small perpendicular residual) beyond the streak's endpoints — a real meteor has none, the validated 2026-07-13 glint scored 3. Measured on the DIFFERENCE image so static stars cancel and cannot be miscounted as fragments.",
                    "Ships in shadow mode: frag_filter off = the metric is logged (frag-shadow entries in meteors_vetoed.json, frag_n/frag_ext on every saved meteor) but nothing is vetoed. Arm only after real meteors confirm they score 0."
                ]
            }
        ]
    }
}

# Major annual meteor showers: name, (start m,d), (end m,d), peak ZHR. Used for
# date-based shower context (which showers are active) — not geometric radiant matching,
# which would need a calibrated fisheye projection.
SHOWERS = [
    ("Quadrantids",     (12, 28), (1, 12), 110),
    ("Lyrids",          (4, 16),  (4, 25), 18),
    ("Eta Aquariids",   (4, 19),  (5, 28), 50),
    ("Delta Aquariids", (7, 12),  (8, 23), 25),
    ("Perseids",        (7, 17),  (8, 24), 100),
    ("Orionids",        (10, 2),  (11, 7), 20),
    ("Leonids",         (11, 6),  (11, 30), 15),
    ("Geminids",        (12, 4),  (12, 17), 150),
    ("Ursids",          (12, 17), (12, 26), 10),
]


def _activeShowers(stamp):
    """Showers active on the given YYYYMMDDHHMMSS date, brightest first."""
    try:
        val = int(stamp[4:6]) * 100 + int(stamp[6:8])
    except Exception:
        return []
    out = []
    for name, (m1, d1), (m2, d2), zhr in SHOWERS:
        a, b = m1 * 100 + d1, m2 * 100 + d2
        if (a <= val <= b) if a <= b else (val >= a or val <= b):
            out.append((zhr, name))
    return [n for _, n in sorted(out, reverse=True)]


# --- optional geometric radiant matching (needs allsky_fisheye + calibration.json) ---
_calibCache = {"done": False, "mod": None, "calib": None}


def _loadCalib():
    """Lazy-load the fisheye calibration + projection library (both optional)."""
    if not _calibCache["done"]:
        _calibCache["done"] = True
        try:
            import allsky_fisheye as fe
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")
            _calibCache["calib"] = fe.load_calibration(p)
            _calibCache["mod"] = fe
            s.log(4, "INFO: meteordetect geometric radiant matching enabled")
        except Exception as ex:
            s.log(1, f"INFO: meteordetect radiant matching disabled ({ex})")
    return _calibCache["mod"], _calibCache["calib"]


def _matchRadiant(p1, p2, showers):
    """Geometric shower attribution for a streak (pixel endpoints), or None.
    Uses current UTC (detection is near-real-time, so it matches the frame time)."""
    mod, calib = _loadCalib()
    if not mod or not calib or not showers:
        return None
    try:
        g = time.gmtime()
        u = (g.tm_year, g.tm_mon, g.tm_mday, g.tm_hour, g.tm_min, g.tm_sec)
        name, _sep = mod.match_radiant(p1, p2, calib, u, showers)
        return name
    except Exception as ex:
        s.log(1, f"WARNING: meteordetect radiant match failed: {ex}")
        return None


# --- star-trail orientation veto (needs the fisheye calibration) ---
_SIDEREAL_DEG_PER_S = 15.041 / 3600.0

def _trailAngleAt(cx, cy):
    """Local diurnal star-trail tangent orientation at pixel (cx,cy), in image
    degrees [0,180), or None if the calibration is unavailable / point is below
    the horizon. A streak parallel to this is a trailed star, not a meteor.

    The exposure length does not matter for the *direction*: we rotate the star's
    sky vector by a small fixed angle about the celestial pole and read off the
    resulting pixel displacement, which is the tangent to its diurnal circle.
    """
    mod, calib = _loadCalib()
    if not mod or not calib:
        return None
    try:
        alt, az = mod.pixel_to_altaz(cx, cy, calib)
        if alt <= 0.5:
            return None
        v = mod._unit(alt, az)
        P = mod._unit(calib["lat"], 0.0)                 # celestial pole direction
        P = P / (np.linalg.norm(P) + 1e-12)
        th = np.radians(_SIDEREAL_DEG_PER_S * 60.0)      # 60 s of rotation → tangent
        v2 = (v * np.cos(th) + np.cross(P, v) * np.sin(th) + P * float(np.dot(P, v)) * (1 - np.cos(th)))
        alt2 = np.degrees(np.arcsin(max(-1.0, min(1.0, float(v2[2])))))
        az2 = np.degrees(np.arctan2(float(v2[0]), float(v2[1]))) % 360.0
        x1, y1 = mod.altaz_to_pixel(alt, az, calib)
        x2, y2 = mod.altaz_to_pixel(alt2, az2, calib)
        return float(np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180.0)
    except Exception:
        return None


def _logVetoed(outdir, stamp, cand, reason, detail):
    """Append a rejected streak to a rolling meteors_vetoed.json for tuning/validation."""
    try:
        path = os.path.join(outdir, "meteors_vetoed.json")
        try:
            log = json.load(open(path)) if os.path.exists(path) else []
        except Exception:
            log = []
        log.append({"time": stamp, "reason": reason, "detail": round(float(detail), 1),
                    "cx": round(cand["cx"], 1), "cy": round(cand["cy"], 1),
                    "len": round(cand["len"], 1), "elong": round(cand["elong"], 1),
                    "ang": round(cand["ang"], 1), "peak": cand.get("peak")})
        json.dump(log[-500:], open(path, "w"), default=float)
    except Exception:
        pass


# --- persistent state between frames (module stays loaded in the postprocess service) ---
_maskCache = {"name": None, "soft": None, "hard": None}
STATE_FILE = os.path.join(s.ALLSKY_TMP, "allsky_meteordetect_state.json")
PREV_FRAME = os.path.join(s.ALLSKY_TMP, "allsky_meteordetect_prev.png")


def _loadMask(maskName, feather, shape):
    """Return (soft float 0..1 mask, hard uint8 mask) matching the frame, cached."""
    if _maskCache["name"] == (maskName, feather) and _maskCache["soft"] is not None \
            and _maskCache["soft"].shape == shape:
        return _maskCache["soft"], _maskCache["hard"]
    hard = None
    if maskName:
        p = os.path.join(s.ALLSKY_OVERLAY, "images", maskName)
        hard = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    if hard is None:
        hard = np.full(shape, 255, np.uint8)
    if hard.shape != shape:
        hard = cv2.resize(hard, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    # soft, feathered edge (indi-allsky lesson: hard edges create false streaks)
    f = s.int(feather)
    if f > 0:
        k = f + (1 - f % 2)  # odd
        soft = cv2.GaussianBlur(hard, (k, k), 0).astype(np.float32) / 255.0
    else:
        soft = hard.astype(np.float32) / 255.0
    _maskCache.update(name=(maskName, feather), soft=soft, hard=hard)
    return soft, hard


def _findStreaks(diff, min_len, min_elong, max_area, diff_thr):
    _, bw = cv2.threshold(diff, diff_thr, 255, cv2.THRESH_BINARY)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    out = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 12 or area > max_area:
            continue
        ys, xs = np.where(lab == i)
        pts = np.column_stack((xs, ys)).astype(np.float32)
        if len(pts) < 5:
            continue
        mean, evec, eval_ = cv2.PCACompute2(pts, mean=None)
        l_major = 4.0 * float(np.sqrt(max(eval_[0, 0], 1e-6)))
        l_minor = 4.0 * float(np.sqrt(max(eval_[1, 0], 1e-6)))
        if l_major < min_len:
            continue
        elong = l_major / (l_minor + 1e-6)
        if elong < min_elong:
            continue
        cx, cy = float(mean[0, 0]), float(mean[0, 1])
        dx, dy = float(evec[0][0]), float(evec[0][1])
        ang = float(np.degrees(np.arctan2(dy, dx)) % 180)
        peak = int(diff[ys, xs].max())        # brightness = peak new-light intensity
        # cast everything to native python floats so the state stays JSON-serialisable
        out.append({
            "cx": cx, "cy": cy, "len": float(l_major), "elong": float(elong), "ang": ang,
            "p1": [cx - dx * l_major / 2, cy - dy * l_major / 2],
            "p2": [cx + dx * l_major / 2, cy + dy * l_major / 2],
            "area": int(area), "peak": peak
        })
    return out


def _dashRuns(gray, p1, p2):
    """Count how many separate bright segments lie along a streak's axis.

    A meteor is a single continuous streak (1 run, sometimes 2 if it tapers);
    a tumbling satellite or a strobing aircraft leaves a DASHED trail — many
    bright/dark alternations. Sampling the intensity along the axis (with a
    small perpendicular max so a slight axis mis-fit still lands on the streak),
    then counting rising edges above a level set relative to the streak's own
    peak, gives a clean separator: on this camera a real meteor scores <=5 and
    a dashed satellite scored 19. Validated on the 2026-07-13 detections."""
    p1 = np.asarray(p1, float); p2 = np.asarray(p2, float)
    L = float(np.hypot(*(p2 - p1)))
    if L < 1.0:
        return 0
    n = max(8, int(L))
    d = (p2 - p1) / L
    perp = np.array([-d[1], d[0]])
    h, w = gray.shape
    vals = np.zeros(n + 1, np.float32)
    for i in range(n + 1):
        pt = p1 + d * (L * i / n)
        m = 0.0
        for o in (-3, -2, -1, 0, 1, 2, 3):     # perpendicular window, robust to mis-fit
            q = pt + perp * o
            x = int(round(q[0])); y = int(round(q[1]))
            if 0 <= x < w and 0 <= y < h:
                v = float(gray[y, x])
                if v > m:
                    m = v
        vals[i] = m
    bg = float(np.percentile(vals, 10)); pk = float(vals.max())
    if pk - bg < 8.0:                          # no real contrast -> not dashed
        return 0
    level = bg + 0.30 * (pk - bg)
    on = vals >= level
    return int(np.sum(on[1:] & ~on[:-1])) + (1 if on[0] else 0)


def _collinearFragments(diff, cx, cy, ang, length, diff_thr,
                        perp_tol=8.0, reach_factor=3.0, area_min=6):
    """Count difference components that lie COLLINEAR with a streak but BEYOND
    its endpoints — the dashed continuation of a fragmented satellite/aircraft
    glint whose faint tail was split into separate sub-threshold pieces.

    The v0.4.0 dash veto only samples the streak's own axis (its continuous
    bright head), so a lone bright head with a broken-up tail passes. This
    walks every diff component and keeps those whose centroid sits within
    ``perp_tol`` px of the streak's infinite axis line and past its own extent
    (|axial| > length/2) out to ``reach_factor``x. A real meteor is a single
    streak with nothing collinear beyond it -> 0; the validated 2026-07-13
    satellite glint scored 3. Measured on the DIFFERENCE image so static stars
    (which cancel there) are never miscounted. Returns (count, max_extent_px)."""
    a = np.radians(ang)
    dx, dy = float(np.cos(a)), float(np.sin(a))
    half = length / 2.0
    reach = half * reach_factor
    _, bw = cv2.threshold(diff, diff_thr, 255, cv2.THRESH_BINARY)
    n, _, stats, cent = cv2.connectedComponentsWithStats(bw, 8)
    cnt = 0
    ext = half
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < area_min:
            continue
        px = float(cent[i][0]) - cx
        py = float(cent[i][1]) - cy
        axial = px * dx + py * dy            # signed distance along the axis
        perp = abs(-px * dy + py * dx)       # distance perpendicular to the axis
        if perp <= perp_tol and half < abs(axial) <= reach:
            cnt += 1
            if abs(axial) > ext:
                ext = abs(axial)
    return cnt, float(ext)


def _angDiff(a, b):
    return min(abs(a - b), 180 - abs(a - b))


def _similar(a, b):
    return np.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"]) < 60 and _angDiff(a["ang"], b["ang"]) < 20


def _progressing(a, b):
    dc = np.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"])
    return 25 < dc < 400 and _angDiff(a["ang"], b["ang"]) < 25


def _readState():
    try:
        with open(STATE_FILE) as fh:
            return json.load(fh)
    except Exception:
        return {"prev_streaks": []}


def _writeState(st):
    try:
        with open(STATE_FILE, "w") as fh:
            json.dump(st, fh, default=float)
    except Exception as ex:
        s.log(0, f"ERROR: meteordetect could not write state: {ex}")


def _drawBrackets(img, streak, colour=(0, 255, 255)):
    """Draw a rotated bounding bracket AROUND the streak, never over it."""
    p1 = np.array(streak["p1"]); p2 = np.array(streak["p2"])
    d = p2 - p1
    L = np.hypot(*d) + 1e-6
    perp = np.array([-d[1], d[0]]) / L
    pad = 18
    a = p1 - d / L * pad; b = p2 + d / L * pad
    for sgn in (1, -1):
        o = perp * pad * sgn
        ca, cb = a + o, b + o
        cv2.line(img, tuple(ca.astype(int)), tuple((ca + d / L * 22).astype(int)), colour, 2)
        cv2.line(img, tuple(cb.astype(int)), tuple((cb - d / L * 22).astype(int)), colour, 2)


def _safeRemove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _saveMeteor(img_path, stamp, streaks, outdir, thumbdir, save_debug):
    """Save the pristine true-colour meteor image + thumbnail + json log. Returns 1/0."""
    img = cv2.imread(img_path)
    if img is None:
        return 0
    os.makedirs(thumbdir, exist_ok=True)
    fname = f"meteors-{stamp}.jpg"
    cv2.imwrite(os.path.join(outdir, fname), img)                       # GALLERY: untouched colours
    cv2.imwrite(os.path.join(thumbdir, fname),
                cv2.resize(img, (0, 0), fx=0.25, fy=0.25))
    if save_debug:
        marked = img.copy()
        for m in streaks:
            _drawBrackets(marked, m)                                    # brackets AROUND, never over
        cv2.imwrite(os.path.join(outdir, f"meteors-{stamp}-marked.jpg"), marked)
    logpath = os.path.join(outdir, "meteors.json")
    try:
        log = json.load(open(logpath)) if os.path.exists(logpath) else []
    except Exception:
        log = []
    showers = _activeShowers(stamp)
    for m in streaks:
        radiant = _matchRadiant(m["p1"], m["p2"], showers)   # geometric attribution
        log.append({"time": stamp, "file": fname,
                    "length": round(m["len"], 1), "angle": round(m["ang"], 1),
                    "elong": round(m["elong"], 1), "peak": m.get("peak"),
                    "cx": round(m["cx"], 1), "cy": round(m["cy"], 1),
                    "p1": [round(m["p1"][0], 1), round(m["p1"][1], 1)],
                    "p2": [round(m["p2"][0], 1), round(m["p2"][1], 1)],
                    "frag_n": m.get("frag_n", 0), "frag_ext": round(m.get("frag_ext", 0.0), 1),
                    "showers": showers, "radiant": radiant})
    try:
        json.dump(log[-2000:], open(logpath, "w"))
    except Exception as ex:
        s.log(1, f"WARNING: meteordetect could not write log: {ex}")
    return 1


def _uploadRemote(outdir, thumbdir, fname):
    """Upload a saved meteor image + thumbnail to the remote website via Allsky's upload.sh.
    Mirrors how keograms are uploaded. Never raises."""
    try:
        if str(s.getSetting("useremotewebsite")).lower() not in ("true", "1", "yes", "on"):
            return
        scripts = s.getEnvironmentVariable("ALLSKY_SCRIPTS") or \
            os.path.join(s.getEnvironmentVariable("ALLSKY_HOME") or os.path.expanduser("~/allsky"), "scripts")
        uploader = os.path.join(scripts, "upload.sh")
        if not os.path.isfile(uploader):
            return
        base = (s.getSetting("remotewebsiteimagedir") or "").rstrip("/")
        remote_dir = f"{base}/meteors" if base else "meteors"
        for local, rdir, tag in (
            (os.path.join(outdir, fname), remote_dir, "Meteor"),
            (os.path.join(thumbdir, fname), remote_dir + "/thumbnails", "MeteorThumb"),
            # the index that drives the chart + gallery — without it the remote
            # page has the images but no data, so both stay empty
            (os.path.join(outdir, "meteors.json"), remote_dir, "MeteorLog"),
        ):
            if os.path.isfile(local):
                subprocess.Popen([uploader, "--silent", "--wait", "--remote-web", local, rdir, fname, tag],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as ex:
        s.log(1, f"WARNING: meteordetect remote upload failed: {ex}")


def _truthy(v):
    """Checkbox args arrive from the flow config as the STRING 'true'/'false';
    'false' is truthy in Python, so parse booleans explicitly."""
    return v is True or (not isinstance(v, bool) and str(v).strip().lower() in ("true", "1", "yes", "on"))


def meteordetect(params, event):
    if s.image is None:
        return "No image available"

    raining, rainFlag = s.raining()
    if rainFlag:
        s.setEnvironmentVariable("AS_METEORCOUNT", "Disabled (rain)")
        return "Raining - meteor detection skipped"

    min_len = s.int(params.get("min_length", 50))
    diff_thr = s.int(params.get("diff_thr", 22))
    min_elong = s.asfloat(params.get("min_elong", 5.0))
    max_area = s.int(params.get("max_area", 6000))
    cloud_frac = s.asfloat(params.get("cloud_frac", 2.0)) / 100.0
    feather = params.get("edge_feather", 35)
    # .get() with defaults so a config saved before these options existed still runs
    dash_filter = _truthy(params.get("dash_filter", True))
    dash_runs = s.int(params.get("dash_runs", 10))
    dash_min_len = s.asfloat(params.get("dash_min_len", 120.0))
    frag_filter = _truthy(params.get("frag_filter", False))   # off = shadow (measure + log, no veto)
    frag_min = s.int(params.get("frag_min", 3))
    frag_min_len = s.asfloat(params.get("frag_min_len", 120.0))
    sat_filter = _truthy(params.get("satellite_filter", True))
    scint_guard = _truthy(params.get("scint_guard", True))
    scint_max = s.int(params.get("scint_max", 8))
    repeat_filter = _truthy(params.get("repeat_filter", True))
    repeat_k = s.int(params.get("repeat_k", 3))
    trail_filter = _truthy(params.get("trail_filter", True))
    trail_tol = s.asfloat(params.get("trail_tol", 12.0))
    upload_remote = _truthy(params.get("upload_remote", True))
    save_debug = _truthy(params.get("save_debug", False))
    debug = _truthy(params.get("debug", False))

    outdir = params["outputdir"].strip()
    if not outdir:
        website = s.getEnvironmentVariable("ALLSKY_WEBSITE")
        if not website:
            website = os.path.join(s.getEnvironmentVariable("ALLSKY_HOME") or os.path.expanduser("~/allsky"),
                                   "html", "allsky")
        outdir = os.path.join(website, "meteors")
    thumbdir = os.path.join(outdir, "thumbnails")

    if debug:
        s.startModuleDebug(metaData["module"])

    gray = cv2.cvtColor(s.image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    soft, hard = _loadMask(params["mask"], feather, gray.shape)

    # previous frame (persisted to disk so it survives restarts)
    prev = cv2.imread(PREV_FRAME, cv2.IMREAD_GRAYSCALE)
    cv2.imwrite(PREV_FRAME, gray.astype(np.uint8))
    if prev is None or prev.shape != gray.shape:
        s.setEnvironmentVariable("AS_METEORCOUNT", "0")
        return "First frame stored, need a second frame to compare"

    # frame difference, remove global offset, apply SOFT mask
    diff = cv2.absdiff(gray, prev.astype(np.float32))
    diff = np.clip(diff - float(np.median(diff)), 0, 255)
    diff_m = (diff * soft).astype(np.uint8)
    if debug:
        s.writeDebugImage(metaData["module"], "diff.png", diff_m)

    # cloud gate
    coverage = float((diff_m > diff_thr).mean() / max(1e-6, (hard > 0).mean()))
    if coverage > cloud_frac:
        s.setEnvironmentVariable("AS_METEORCOUNT", "0")
        st = _readState(); st["prev_streaks"] = []; _writeState(st)
        return f"Cloudy frame skipped (coverage {coverage*100:.1f}%)"

    streaks = _findStreaks(diff_m, min_len, min_elong, max_area, diff_thr)

    # tag each streak with its dashed-segment count (measured on the true-colour
    # frame the streak was just captured in) so the dashed-trail veto can run when
    # the candidate is confirmed one frame later. Cheap; only long streaks matter.
    if dash_filter:
        for st_ in streaks:
            st_["dash_runs"] = (_dashRuns(gray, st_["p1"], st_["p2"])
                                if st_["len"] >= dash_min_len else 0)

    # tag each long streak with its collinear-fragment count on the DIFFERENCE
    # image (static stars cancel there). Measured always so the shadow metric is
    # gathered even while frag_filter is off; only long streaks are worth testing.
    for st_ in streaks:
        if st_["len"] >= frag_min_len:
            fn, fx = _collinearFragments(diff_m, st_["cx"], st_["cy"],
                                         st_["ang"], st_["len"], diff_thr)
            st_["frag_n"], st_["frag_ext"] = fn, fx
        else:
            st_["frag_n"], st_["frag_ext"] = 0, st_["len"] / 2.0

    # scintillation guard: a clear starry night produces many tiny star-twinkle
    # streaks. If the frame is that noisy, keep only a clearly dominant streak
    # (a genuine bright meteor stands well above the noise), else skip the frame.
    if scint_guard and len(streaks) > scint_max:
        ordered = sorted(streaks, key=lambda st_: st_["len"], reverse=True)
        second = ordered[1]["len"] if len(ordered) > 1 else 0.0
        if ordered[0]["len"] >= 1.6 * second:
            streaks = [ordered[0]]
        else:
            # too noisy to trust: drop pending unconfirmed and skip, like a cloudy frame
            st = _readState()
            for entry in st.get("pending", []):
                _safeRemove(entry["img_path"])
            st["prev_streaks"] = []
            st["pending"] = []
            _writeState(st)
            s.setEnvironmentVariable("AS_METEORCOUNT", "0")
            return "Scintillation-dominated frame skipped (clear sky, star twinkle)"

    state = _readState()
    prev_streaks = state.get("prev_streaks", [])
    pending = state.get("pending", [])   # candidates from last frame awaiting confirmation

    # rolling "hot spot" memory for the recurrence veto: [cx, cy, t] of every streak
    # from earlier frames. A trailed star / scintillation / bloom / fixed reflection
    # keeps firing near the same spot; a real meteor appears exactly once, so it can
    # never accumulate here and is never vetoed by recurrence.
    REPEAT_RADIUS, REPEAT_WINDOW_S = 55.0, 1500.0
    now_t = time.time()
    hotspots = [h for h in state.get("hotspots", []) if now_t - h[2] <= REPEAT_WINDOW_S]

    def _recurrence(cand):
        r2 = REPEAT_RADIUS ** 2
        return sum(1 for h in hotspots
                   if (h[0] - cand["cx"]) ** 2 + (h[1] - cand["cy"]) ** 2 <= r2)

    saved, moving, vetoed = 0, 0, 0

    # --- 1) resolve last frame's pending candidates ---
    # A real meteor is present in exactly one frame, so it shows up in TWO consecutive
    # difference images at the SAME location (its appearance, then its disappearance).
    # We confirm a candidate only if the current frame repeats it at the same spot AND
    # it is not a moving track, a recurring position, or aligned with the star trails.
    for entry in pending:
        keep = []
        for cand in entry["streaks"]:
            if sat_filter and any(_progressing(cur, cand) for cur in streaks):
                moving += 1
                continue
            if not any(_similar(cur, cand) for cur in streaks):
                continue  # no same-location disappearance -> flicker -> discard
            rec = _recurrence(cand) if repeat_filter else 0
            if repeat_filter and rec >= repeat_k:
                vetoed += 1
                _logVetoed(outdir, entry["stamp"], cand, "repeat", rec)
                continue
            if trail_filter and cand["len"] <= 130.0:          # long/bright fireballs exempt
                ta = _trailAngleAt(cand["cx"], cand["cy"])
                if ta is not None and _angDiff(cand["ang"], ta) <= trail_tol:
                    vetoed += 1
                    _logVetoed(outdir, entry["stamp"], cand, "trail", _angDiff(cand["ang"], ta))
                    continue
            if dash_filter and cand["len"] >= dash_min_len and cand.get("dash_runs", 0) >= dash_runs:
                vetoed += 1
                _logVetoed(outdir, entry["stamp"], cand, "dashed", cand.get("dash_runs", 0))
                continue
            # fragmented-trail check. Armed (frag_filter on) it vetoes; off it is
            # shadow-only: log a frag-shadow entry for tuning but keep the meteor,
            # so we learn what it WOULD reject without risking a real meteor yet.
            if cand["len"] >= frag_min_len and cand.get("frag_n", 0) >= frag_min:
                if frag_filter:
                    vetoed += 1
                    _logVetoed(outdir, entry["stamp"], cand, "fragmented", cand.get("frag_n", 0))
                    continue
                _logVetoed(outdir, entry["stamp"], cand, "frag-shadow", cand.get("frag_n", 0))
            keep.append(cand)
        if keep:
            n = _saveMeteor(entry["img_path"], entry["stamp"], keep,
                            outdir, thumbdir, save_debug)
            saved += n
            if n and upload_remote:
                _uploadRemote(outdir, thumbdir, f"meteors-{entry['stamp']}.jpg")
        _safeRemove(entry["img_path"])

    # --- 2) collect NEW candidates from the current frame (deferred to next frame) ---
    new_cands = []
    for st_ in streaks:
        if sat_filter and any(_progressing(st_, p) for p in prev_streaks):
            moving += 1
            continue
        if any(_similar(st_, p) for p in prev_streaks):
            continue  # disappearance of an already handled streak -> de-dupe
        new_cands.append(st_)

    new_pending = []
    if new_cands:
        stamp = time.strftime("%Y%m%d%H%M%S")
        stash = os.path.join(s.ALLSKY_TMP, f"allsky_meteordetect_pending_{stamp}.jpg")
        cv2.imwrite(stash, s.image)          # stash TRUE-COLOUR frame for later save
        new_pending.append({"img_path": stash, "stamp": stamp, "streaks": new_cands})

    # remember this frame's streak positions for the recurrence veto (rolling, pruned)
    hotspots.extend([round(st_["cx"], 1), round(st_["cy"], 1), now_t] for st_ in streaks)
    state["hotspots"] = hotspots[-400:]
    state["prev_streaks"] = streaks
    state["pending"] = new_pending
    _writeState(state)

    s.setEnvironmentVariable("AS_METEORCOUNT", str(saved))
    s.setEnvironmentVariable("AS_METEORMOVING", str(moving))
    s.setEnvironmentVariable("AS_METEORVETOED", str(vetoed))
    result = (f"{saved} meteor(s) confirmed, {moving} moving rejected, "
              f"{vetoed} artifact(s) vetoed, {len(new_cands)} new candidate(s) pending, "
              f"{len(streaks)} streak(s) total")
    s.log(4, f"INFO: {result}")
    return result


def meteordetect_cleanup():
    moduleData = {
        "metaData": metaData,
        "cleanup": {
            "files": {STATE_FILE, PREV_FRAME},
            "env": {"AS_METEORCOUNT", "AS_METEORMOVING", "AS_METEORVETOED"}
        }
    }
    s.cleanupModule(moduleData)
