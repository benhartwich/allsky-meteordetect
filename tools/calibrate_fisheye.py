#!/usr/bin/env python3
"""Fisheye all-sky calibration: fit (cx, cy, R, rot, flip) so that pixel <-> (alt,az).

Detect bright stars in a night frame, compute the true alt/az of catalogue bright
stars at the capture time/location with ephem, auto-match, and least-squares fit an
equidistant fisheye projection. Prints residual RMS in pixels and degrees.
"""
import sys, re, math, json
import numpy as np, cv2, ephem
from scipy.optimize import least_squares

LAT, LON = "48.136010", "14.389510"          # N, E
TZ_OFFSET_H = 2                               # CEST = UTC+2 (filenames are local)

# Bright stars ephem knows by name (Hipparcos bright catalogue subset)
CAT = ["Sirius","Arcturus","Vega","Capella","Rigel","Procyon","Betelgeuse","Altair",
       "Aldebaran","Antares","Spica","Pollux","Fomalhaut","Deneb","Regulus","Castor",
       "Bellatrix","Elnath","Alnilam","Alnitak","Alioth","Mirfak","Dubhe","Alkaid",
       "Mizar","Alhena","Polaris","Alphard","Denebola","Rasalhague","Kochab","Vindemiatrix",
       "Eltanin","Alphecca","Enif","Sadr","Nunki","Kaus Australis","Menkalinan","Alderamin",
       "Schedar","Caph","Algol","Hamal","Diphda","Markab","Scheat","Algieba",
       "Alcyone","Merak","Phecda","Megrez","Alcor","Cor Caroli","Izar","Muphrid",
       "Zubenelgenubi","Zubeneschamali","Unukalhai","Rasalgethi","Sabik","Yed Prior",
       "Ruchbah","Almach","Mirach","Alpheratz","Zosma","Chertan","Tarazed","Albireo",
       "Rukbat","Kaus Media","Kaus Borealis","Ascella","Gienah","Sadalsuud","Sadalmelik",
       "Homam","Matar","Vega","Wega","Rastaban","Etamin","Grumium","Alnath"]


def frame_utc(path):
    m = re.search(r'image-(\d{14})', path)
    s = m.group(1)
    dt = ephem.Date((int(s[0:4]), int(s[4:6]), int(s[6:8]),
                     int(s[8:10]) - TZ_OFFSET_H, int(s[10:12]), int(s[12:14])))
    return dt


def detect_stars(gray, maxN=340):
    """Return list of (x,y,peak) for compact bright star-like blobs."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k)     # isolate small bright features
    thr = max(10, int(np.percentile(tophat, 99.0)))
    _, bw = cv2.threshold(tophat, thr, 255, cv2.THRESH_BINARY)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(bw, 8)
    out = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 2 or area > 80:
            continue
        x, y = cent[i]
        peak = int(gray[int(round(y)), int(round(x))])
        out.append((float(x), float(y), peak))
    out.sort(key=lambda t: -t[2])
    return out[:maxN]


def catalog_altaz(utc):
    obs = ephem.Observer(); obs.lat = LAT; obs.lon = LON; obs.date = utc
    obs.pressure = 0                                          # ignore refraction
    stars, seen = [], set()
    for name in CAT:
        if name in seen:
            continue
        seen.add(name)
        try:
            b = ephem.star(name); b.compute(obs)
            alt, az = math.degrees(b.alt), math.degrees(b.az)
            if alt > 15 and float(b.mag) < 3.8:               # bright, avoid horizon/trees
                stars.append((name, alt, az, float(b.mag)))
        except Exception:
            pass
    stars.sort(key=lambda t: t[3])                            # brightest first
    return stars


def project(alt, az, p):
    """(alt,az) deg -> (x,y) px. p=(cx,cy,a1,a3,rot,flip).
    Radial fisheye with cubic distortion: r = a1*t + a3*t^3, t=zenithangle/90.
    Pure equidistant is a3=0. North-up, azimuth handled by rot+flip."""
    cx, cy, a1, a3, rot, flip = p
    t = (90.0 - alt) / 90.0
    r = a1 * t + a3 * t**3
    ang = math.radians(rot + flip * az)
    return cx + r * math.sin(ang), cy - r * math.cos(ang)


def estimate_disk(gray):
    _, bw = cv2.threshold(gray, 8, 255, cv2.THRESH_BINARY)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        h, w = gray.shape; return w/2, h/2, min(w, h)/2
    c = max(cnts, key=cv2.contourArea)
    (cx, cy), R = cv2.minEnclosingCircle(c)      # circle enclosing the bright sky disk
    return float(cx), float(cy), float(R)


def match(stars, detected, p, tol):
    dets = np.array([[d[0], d[1]] for d in detected])
    pairs = []
    for name, alt, az, mag in stars:
        px, py = project(alt, az, p)
        d = np.hypot(dets[:, 0] - px, dets[:, 1] - py)
        j = int(np.argmin(d))
        if d[j] < tol:
            pairs.append((name, alt, az, dets[j, 0], dets[j, 1], d[j]))
    return pairs


def match_mutual(stars, detected, p, tol):
    """Mutual nearest-neighbour match: keep a (star,blob) pair only if the blob is the
    star's nearest projection AND no other star projects closer to that blob."""
    dets = np.array([[d[0], d[1]] for d in detected])
    proj = np.array([project(a, z, p) for _, a, z, _ in stars])
    pairs = []
    for i, (name, alt, az, mag) in enumerate(stars):
        dd = np.hypot(dets[:, 0] - proj[i, 0], dets[:, 1] - proj[i, 1])
        j = int(np.argmin(dd))
        if dd[j] >= tol:
            continue
        # is star i the closest star projection to blob j?
        dstar = np.hypot(proj[:, 0] - dets[j, 0], proj[:, 1] - dets[j, 1])
        if int(np.argmin(dstar)) == i:
            pairs.append((name, alt, az, dets[j, 0], dets[j, 1], dd[j]))
    return pairs


def fit(pairs, p0, flip, free_a3):
    def resid(q):
        a3 = q[3] if free_a3 else 0.0
        r = []
        for name, alt, az, dx, dy, _ in pairs:
            px, py = project(alt, az, (q[0], q[1], q[2], a3, q[4], flip))
            r += [px - dx, py - dy]
        return r
    sol = least_squares(resid, p0, loss="soft_l1", f_scale=8.0)
    q = list(sol.x)
    if not free_a3:
        q[3] = 0.0
    res = np.array(resid(q)).reshape(-1, 2)
    rms = float(np.sqrt((res**2).sum(axis=1).mean()))
    return q, rms


def main(path):
    img = cv2.imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    utc = frame_utc(path)
    print(f"frame {path}\n  UTC {ephem.Date(utc)}  size {W}x{H}")

    detected = detect_stars(gray)
    stars = catalog_altaz(utc)
    print(f"  detected {len(detected)} star blobs; {len(stars)} catalogue stars")
    cx0, cy0, R0 = estimate_disk(gray)
    print(f"  disk estimate cx={cx0:.0f} cy={cy0:.0f} R={R0:.0f}")

    def refine_from(seed, flip, verbose=False):
        """Generous->tight tolerance so distant zenith stars are pulled in before the
        fit tightens. Returns (params, rms, inliers<1deg, n_matched)."""
        p = list(seed)
        rms = float("nan")
        for it, tol in enumerate((60, 46, 35, 27, 21, 17, 14, 12)):
            pairs = match_mutual(stars, detected, (p[0],p[1],p[2],p[3],p[4],flip), tol)
            if len(pairs) < 6:
                if verbose: print(f"    iter {it} tol={tol}: {len(pairs)} matches, stop")
                return p, float("inf"), 0, len(pairs)
            p, rms = fit(pairs, p, flip, free_a3=(it >= 3))
            if verbose:
                print(f"    iter {it} tol={tol}: {len(pairs)} matches RMS={rms:.1f}px "
                      f"cx={p[0]:.0f} cy={p[1]:.0f} a1={p[2]:.0f} a3={p[3]:.0f} rot={p[4]%360:.1f}")
        fp = match_mutual(stars, detected, (p[0],p[1],p[2],p[3],p[4],flip), 13)
        inl = sum(1 for pr in fp if pr[5] < 13)
        return p, rms, inl, len(fp)

    # -- deterministic global grid search (equidistant), scored by hard star-inliers --
    from scipy.spatial import cKDTree
    tree = cKDTree(np.array([[d[0], d[1]] for d in detected]))
    salt = np.array([s_[1] for s_ in stars]); saz = np.array([s_[2] for s_ in stars])
    def hard_score(cx, cy, R, rot, flip, thr=18.0):
        t = (90.0 - salt) / 90.0
        r = R * t
        ang = np.radians(rot + flip * saz)
        xs = cx + r * np.sin(ang); ys = cy - r * np.cos(ang)
        d, _ = tree.query(np.column_stack([xs, ys]))
        return int((d < thr).sum())
    best = (-1, None)
    for flip in (1.0, -1.0):
        for cx in range(int(W/2)-45, int(W/2)+46, 30):
            for cy in range(int(H/2)-45, int(H/2)+46, 30):
                for R in range(1150, 1451, 40):
                    for rot in range(0, 360, 3):
                        sc = hard_score(cx, cy, R, rot, flip)
                        if sc > best[0]:
                            best = (sc, (cx, cy, R, 0.0, float(rot), flip))
    sc, gp = best
    flip = gp[5]
    print(f"  GRID best: {sc}/{len(stars)} stars aligned @18px  "
          f"cx={gp[0]} cy={gp[1]} R={gp[2]} rot={gp[4]:.0f} flip={flip:.0f}")
    print("  refine from grid winner:")
    p, rms, inl, nm = refine_from([gp[0], gp[1], gp[2], 0.0, gp[4]], flip, verbose=True)
    print(f"  RESULT inliers(<1deg)={inl} matched={nm} RMS={rms:.2f}px rot={p[4]%360:.2f}")
    # residuals for ALL bright stars (mag<2) to check zenith vs horizon coverage
    bright = [(n,a,z) for (n,a,z,m) in stars if m < 2.2]
    dets = np.array([[d[0],d[1]] for d in detected])
    print("  bright-star check (nearest blob distance):")
    for n,a,z in sorted(bright, key=lambda t:-t[1]):
        px,py = project(a,z,(p[0],p[1],p[2],p[3],p[4],flip))
        d = float(np.hypot(dets[:,0]-px, dets[:,1]-py).min())
        print(f"    {n:14s} alt={a:5.1f} az={z:6.1f}  nearest blob={d:5.1f}px")

    R_eff = p[2] + p[3]                                       # radius at the horizon (t=1)
    deg_per_px = 90.0 / R_eff
    final = (p[0], p[1], p[2], p[3], p[4], flip)
    calib = {"model": "cubic", "cx": round(p[0], 2), "cy": round(p[1], 2),
             "a1": round(p[2], 3), "a3": round(p[3], 3), "R_horizon": round(R_eff, 2),
             "rot": round(p[4] % 360, 3), "flip": int(flip),
             "rms_px": round(rms, 2), "rms_deg": round(rms*deg_per_px, 3),
             "n_stars": inl, "utc": str(ephem.Date(utc)),
             "lat": LAT, "lon": LON, "W": W, "H": H}
    print("\nCALIBRATION:", json.dumps(calib, indent=2))

    # debug overlay: detected blobs (cyan), catalogue projections (yellow x + name), match links
    ov = img.copy()
    for x, y, pk in detected:
        cv2.circle(ov, (int(x), int(y)), 6, (255, 255, 0), 1)
    goodpairs = match_mutual(stars, detected, final, 18)
    print("  matched stars (name, alt, az, residual px):")
    for name, alt, az, dx, dy, dist in sorted(goodpairs, key=lambda t: t[5]):
        print(f"    {name:16s} alt={alt:5.1f} az={az:6.1f}  res={dist:5.1f}px")
    finalpairs = match(stars, detected, final, tol=1e9)
    for name, alt, az, dx, dy, dist in finalpairs:
        px, py = project(alt, az, final)
        col = (0, 255, 0) if dist < 3*rms else (0, 0, 255)
        cv2.drawMarker(ov, (int(px), int(py)), (0, 255, 255), cv2.MARKER_TILTED_CROSS, 22, 2)
        cv2.line(ov, (int(px), int(py)), (int(dx), int(dy)), col, 1)
        cv2.putText(ov, name, (int(px)+12, int(py)-6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 1)
    cv2.drawMarker(ov, (int(p[0]), int(p[1])), (255,0,255), cv2.MARKER_CROSS, 40, 2)  # zenith
    out = path.rsplit("/",1)[-1].replace(".jpg","_calib.jpg")
    outp = "/tmp/claude-1001/-home-allsky/08ef9600-2e9b-42e8-8903-1884f475f31c/scratchpad/"+out
    cv2.imwrite(outp, ov)
    print("overlay:", outp)
    return calib


if __name__ == "__main__":
    main(sys.argv[1])
