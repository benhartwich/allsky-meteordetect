#!/usr/bin/env python3
"""Backfill the Allsky WebUI meteor folders from the website gallery.

allsky_meteordetect before v0.5.0 wrote every hit flat into the website's
``meteors/`` folder. From v0.5.0 each hit is *additionally* filed under
``images/<day>/meteors/``, which is the layout the Allsky WebUI's Meteors page
browses. This tool performs that filing once for the meteors already on disk, so
the page is not empty until the next detection.

For each ``meteors-<stamp>.jpg`` in the website folder it writes, under the
night's day folder:

  meteors/meteors-<stamp>.jpg             copied
  meteors/meteors-<stamp>-marked.jpg      copied, or redrawn from the logged
                                          streak endpoints if never saved
  meteors/meteors-<stamp>.json            sidecar with this image's streaks,
                                          taken from the rolling meteors.json
  meteorsthumbnail/meteors-<stamp>*.jpg   thumbnails, copied or generated

Thumbnails sit in a sibling folder rather than a meteors/thumbnails/ subfolder,
the way Allsky 2025 stores keogram and startrails thumbnails. Anything an older
version left in meteors/thumbnails/ is moved across.

The day folder follows Allsky's own convention: the night's *evening* date, i.e.
the timestamp shifted back 12 hours, matching ``DATE_NAME`` in saveImage.sh. A
meteor at 03:15 on the 19th therefore belongs to ``images/20260918/``.

Nothing in the website folder is moved, rewritten or deleted -- files are copied
out of it. Re-running is safe: existing destination files are left alone unless
``--force`` is given.

Usage:
    tools/backfill_webui.py --dry-run          # show what would happen
    tools/backfill_webui.py                    # do it
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta

import cv2

STAMP_RE = re.compile(r"^meteors-(\d{14})\.(jpg|png)$", re.I)


def _prepareEnvironment(home):
    """allsky_shared aborts at import unless these exist. Fill in the ones the
    running Allsky would have exported, so the tool can reuse the module's own
    bracket drawing instead of keeping a second copy of it."""
    os.environ.setdefault("ALLSKY_HOME", home)
    os.environ.setdefault("ALLSKY_TMP", os.path.join(home, "tmp"))
    os.environ.setdefault("ALLSKY_SCRIPTS", os.path.join(home, "scripts"))
    os.environ.setdefault("ALLSKY_OVERLAY", os.path.join(home, "config", "overlay"))
    os.environ.setdefault("SETTINGS_FILE", os.path.join(home, "config", "settings.json"))


def _loadModule(home):
    _prepareEnvironment(home)
    sys.path.insert(0, os.path.join(home, "scripts", "modules"))
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import allsky_meteordetect as m           # noqa: E402  (needs the env above)
    return m


def _dayFolder(stamp):
    """Allsky's day-folder name for a timestamp: the evening date, 12 hours back."""
    return (datetime.strptime(stamp, "%Y%m%d%H%M%S") - timedelta(hours=12)).strftime("%Y%m%d")


def _entriesByFile(website):
    """Group the rolling meteors.json by image name. Missing or unreadable is not
    fatal -- the images are still worth filing, just without metadata."""
    path = os.path.join(website, "meteors.json")
    grouped = {}
    try:
        with open(path) as fh:
            log = json.load(fh)
    except FileNotFoundError:
        print(f"note: {path} not found; sidecars will be empty")
        return grouped
    except Exception as ex:
        print(f"note: could not read {path} ({ex}); sidecars will be empty")
        return grouped
    for entry in log:
        name = entry.get("file")
        if name:
            grouped.setdefault(name, []).append(entry)
    return grouped


def _copy(src, dst, force, dry, stats):
    if not os.path.isfile(src):
        return False
    if os.path.exists(dst) and not force:
        stats["skipped"] += 1
        return False
    if not dry:
        shutil.copy2(src, dst)
    stats["copied"] += 1
    return True


def _thumbnail(src, dst, force, dry, stats):
    """Copy the existing thumbnail, or make one the way the module does."""
    if os.path.exists(dst) and not force:
        stats["skipped"] += 1
        return
    if not dry:
        img = cv2.imread(src)
        if img is None:
            print(f"  ! unreadable, no thumbnail: {src}")
            return
        cv2.imwrite(dst, cv2.resize(img, (0, 0), fx=0.25, fy=0.25))
    stats["generated"] += 1


def _marked(module, image, entries, dst, thumbDir, force, dry, stats):
    """Redraw the marked copy from the logged streak endpoints. Pre-v0.5.0 the
    marked copy was off by default, so for most historical meteors there is no
    file to copy -- but meteors.json kept p1/p2, which is all the brackets need."""
    if os.path.exists(dst) and not force:
        stats["skipped"] += 1
        return False
    streaks = [e for e in entries if isinstance(e.get("p1"), list) and isinstance(e.get("p2"), list)]
    if not streaks:
        return False
    if not dry:
        img = cv2.imread(image)
        if img is None:
            print(f"  ! unreadable, no marked copy: {image}")
            return False
        for streak in streaks:
            module._drawBrackets(img, {"p1": streak["p1"], "p2": streak["p2"]})
        cv2.imwrite(dst, img)
        cv2.imwrite(os.path.join(thumbDir, os.path.basename(dst)),
                    cv2.resize(img, (0, 0), fx=0.25, fy=0.25))
    stats["redrawn"] += 1
    return True


def _migrateOldThumbnails(images, thumbDirName, dry):
    """Move thumbnails an older version left in images/<day>/meteors/thumbnails/
    into the sibling images/<day>/<thumbDirName>/, then drop the emptied folder.
    A file already present at the destination wins; the old copy is removed."""
    moved = 0
    for day in sorted(os.listdir(images)):
        old = os.path.join(images, day, "meteors", "thumbnails")
        if not os.path.isdir(old):
            continue
        new = os.path.join(images, day, thumbDirName)
        if not dry:
            os.makedirs(new, exist_ok=True)
        for name in sorted(os.listdir(old)):
            src, dst = os.path.join(old, name), os.path.join(new, name)
            if not os.path.isfile(src):
                continue
            if not dry:
                if os.path.exists(dst):
                    os.remove(src)
                else:
                    shutil.move(src, dst)
            moved += 1
        if not dry:
            try:
                os.rmdir(old)            # only succeeds once it is empty
            except OSError:
                print(f"  ! left in place, not empty: {old}")
    return moved


def main():
    home = os.environ.get("ALLSKY_HOME") or os.path.expanduser("~/allsky")

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--website", help="website meteors folder "
                                      "(default: $ALLSKY_WEBSITE/meteors)")
    ap.add_argument("--images", help="Allsky images folder "
                                     "(default: $ALLSKY_IMAGES or <home>/images)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--force", action="store_true", help="overwrite destination files")
    ap.add_argument("--no-marked", action="store_true",
                    help="do not redraw marked copies for meteors that never had one")
    ap.add_argument("--existing-days-only", action="store_true",
                    help="skip meteors whose day folder no longer exists, instead of "
                         "creating it (old nights whose images were purged would "
                         "otherwise reappear as day rows holding only meteors)")
    args = ap.parse_args()

    website = args.website or os.path.join(
        os.environ.get("ALLSKY_WEBSITE") or os.path.join(home, "html", "allsky"), "meteors")
    images = args.images or os.environ.get("ALLSKY_IMAGES") or os.path.join(home, "images")

    if not os.path.isdir(website):
        sys.exit(f"ERROR: website meteors folder not found: {website}")
    if not os.path.isdir(images):
        sys.exit(f"ERROR: images folder not found: {images}")

    module = _loadModule(home)
    grouped = _entriesByFile(website)

    names = sorted(n for n in os.listdir(website) if STAMP_RE.match(n))
    if not names:
        sys.exit(f"No meteors-<stamp>.jpg files in {website}; nothing to do.")

    print(f"website : {website}")
    print(f"images  : {images}")
    print(f"meteors : {len(names)}"
          f"{'   (DRY RUN -- nothing will be written)' if args.dry_run else ''}\n")

    moved = _migrateOldThumbnails(images, module.WEBUI_THUMB_DIR, args.dry_run)

    stats = {"copied": 0, "generated": 0, "redrawn": 0, "skipped": 0,
             "sidecars": 0, "no_metadata": 0, "skipped_days": 0}
    newDays, touchedDays = set(), set()

    for name in names:
        stamp = STAMP_RE.match(name).group(1)
        day = _dayFolder(stamp)
        dayDir = os.path.join(images, day)
        meteorDir = os.path.join(dayDir, "meteors")
        thumbDir = os.path.join(dayDir, module.WEBUI_THUMB_DIR)

        if not os.path.isdir(dayDir):
            if args.existing_days_only:
                stats["skipped_days"] += 1
                continue
            newDays.add(day)
        touchedDays.add(day)

        if not args.dry_run:
            os.makedirs(meteorDir, exist_ok=True)
            os.makedirs(thumbDir, exist_ok=True)

        _copy(os.path.join(website, name), os.path.join(meteorDir, name),
              args.force, args.dry_run, stats)

        srcThumb = os.path.join(website, "thumbnails", name)
        dstThumb = os.path.join(thumbDir, name)
        if os.path.isfile(srcThumb):
            _copy(srcThumb, dstThumb, args.force, args.dry_run, stats)
        else:
            _thumbnail(os.path.join(website, name), dstThumb, args.force, args.dry_run, stats)

        entries = grouped.get(name, [])
        if not entries:
            stats["no_metadata"] += 1

        base, ext = os.path.splitext(name)
        markedName = f"{base}-marked{ext}"
        srcMarked = os.path.join(website, markedName)
        if os.path.isfile(srcMarked):
            _copy(srcMarked, os.path.join(meteorDir, markedName),
                  args.force, args.dry_run, stats)
            srcMarkedThumb = os.path.join(website, "thumbnails", markedName)
            dstMarkedThumb = os.path.join(thumbDir, markedName)
            if os.path.isfile(srcMarkedThumb):
                _copy(srcMarkedThumb, dstMarkedThumb, args.force, args.dry_run, stats)
            else:
                _thumbnail(srcMarked, dstMarkedThumb, args.force, args.dry_run, stats)
        elif not args.no_marked:
            _marked(module, os.path.join(website, name), entries,
                    os.path.join(meteorDir, markedName), thumbDir,
                    args.force, args.dry_run, stats)

        sidecar = os.path.join(meteorDir, f"{base}.json")
        if not os.path.exists(sidecar) or args.force:
            if not args.dry_run:
                module._writeJson(sidecar, entries)
            stats["sidecars"] += 1

    print(f"days touched      : {len(touchedDays)}")
    if newDays:
        print(f"day folders created: {len(newDays)} "
              f"({', '.join(sorted(newDays)[:6])}{' ...' if len(newDays) > 6 else ''})")
        print("                     these nights' images were purged; they will now "
              "appear in the WebUI day list holding only meteors.")
    if stats["skipped_days"]:
        print(f"skipped (no day folder): {stats['skipped_days']}")
    if moved:
        print(f"thumbnails moved  : {moved}  (meteors/thumbnails/ -> {module.WEBUI_THUMB_DIR}/)")
    print(f"files copied      : {stats['copied']}")
    print(f"thumbnails made   : {stats['generated']}")
    print(f"marked redrawn    : {stats['redrawn']}")
    print(f"sidecars written  : {stats['sidecars']}")
    if stats["no_metadata"]:
        print(f"  of those, empty : {stats['no_metadata']} "
              "(no entry in the rolling meteors.json; the image still browses, "
              "the metadata columns show '-')")
    if stats["skipped"]:
        print(f"already present   : {stats['skipped']}  (use --force to overwrite)")
    if args.dry_run:
        print("\nDry run -- nothing was written. Re-run without --dry-run to apply.")


if __name__ == "__main__":
    main()
