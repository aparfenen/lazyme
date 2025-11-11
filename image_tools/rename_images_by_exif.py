#!/usr/bin/env python3
"""
rename_images_by_exif.py

Rename image files using EXIF/metadata (DateTimeOriginal + subseconds + GPS if present).
Relies on `exiftool` being installed and available in PATH.

Usage examples:
  # dry run (default) - shows proposed renames
  python3 rename_images_by_exif.py /path/to/folder --dry-run

  # actually rename
  python3 rename_images_by_exif.py /path/to/folder

  # recursive
  python3 rename_images_by_exif.py /path/to/folder --recursive

  # copy instead of move (keeps originals)
  python3 rename_images_by_exif.py /path/to/folder --copy

Notes:
 - Filenames format: YYYYMMDD_HHMMSS_mmm[_latLAT_lonLON]_{origbasename}.{ext}
 - If no EXIF date found, falls back to filesystem modification time.
 - If both latitude/longitude available, includes them rounded to 4 decimals.
 - Ensures unique target names by appending -1, -2 ... if needed.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

# ---------- Helpers ----------
def check_exiftool():
    """Return path to exiftool or raise."""
    from shutil import which
    path = which("exiftool")
    if not path:
        raise FileNotFoundError(
            "exiftool not found. Install: macOS: `brew install exiftool` ; "
            "Debian/Ubuntu: `sudo apt install libimage-exiftool-perl`"
        )
    return path

def run_exiftool_json(exiftool_path, filepath):
    """Call exiftool -j -n (numeric coords) and return parsed JSON dict or None."""
    try:
        res = subprocess.run([exiftool_path, "-j", "-n", filepath],
                             capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        if not data:
            return None
        return data[0]
    except subprocess.CalledProcessError as e:
        print(f"exiftool error for {filepath}: {e}", file=sys.stderr)
        return None

def safe_filename(s):
    """Make filename safe for most filesystems: remove/replace problematic chars."""
    # keep unicode; replace slashes and control characters
    for ch in ('/', '\\', ':', '*', '?', '"', '<', '>', '|'):
        s = s.replace(ch, '_')
    s = s.strip()
    # additionally collapse multiple spaces
    s = "_".join(s.split())
    return s

def format_timestamp_from_exif(exif):
    """
    Try DateTimeOriginal (or CreateDate) + SubSecTimeOriginal/SubSecTime to form microsecond accuracy.
    Returns (timestamp_string, datetime_obj) or (None, None)
    """
    # exiftool usually provides 'DateTimeOriginal' key
    dkeys = ["DateTimeOriginal", "CreateDate", "ModifyDate"]
    subsec_keys = ["SubSecTimeOriginal", "SubSecTime", "SubSecTimeDigitized"]
    dt_value = None
    subsec = None
    for k in dkeys:
        if k in exif:
            dt_value = exif[k]
            break
    for k in subsec_keys:
        if k in exif:
            subsec = exif[k]
            break

    if not dt_value:
        return None, None

    # exiftool returns "YYYY:MM:DD HH:MM:SS" (string) in default. If numeric output (-n) sometimes different
    # try to parse common format
    try:
        # ensure we handle when exif gives numeric epoch? but typically string.
        if isinstance(dt_value, (int, float)):
            dt = datetime.fromtimestamp(dt_value)
            msec = int(subsec[:3]) if subsec else 0
        else:
            # Replace first two ':' with '-' to parse easily
            # Example: "2025:11:11 17:12:25"
            s = dt_value
            # some exiftool outputs already ISO-like, but handle both
            s = s.replace(":", "-", 2)
            # now parse
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            msec = int(subsec[:3]) if subsec else 0
        timestamp_str = f"{dt:%Y%m%d}_{dt:%H%M%S}_{msec:03d}"
        return timestamp_str, dt
    except Exception as e:
        return None, None

def format_latlon(exif):
    """Return formatted lat/lon string if both present, else None."""
    lat = exif.get("GPSLatitude")
    lon = exif.get("GPSLongitude")
    # exiftool with -n returns numeric floats for GPSLatitude/GPSLongitude
    if lat is None or lon is None:
        # sometimes tags are 'GPSLatitudeRef'/'GPSLongitudeRef' with DMS strings; skip complicated parsing here
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        return f"lat{lat_f:.4f}_lon{lon_f:.4f}"
    except Exception:
        return None

def get_fallback_mtime(filepath):
    """If no EXIF time, use filesystem modification time as YYYYMMDD_HHMMSS_000"""
    t = os.path.getmtime(filepath)
    dt = datetime.fromtimestamp(t)
    return f"{dt:%Y%m%d}_{dt:%H%M%S}_000", dt

def unique_target_path(dest_dir, base_name, ext):
    """If file exists, append -1, -2 ..."""
    candidate = f"{base_name}{ext}"
    full = os.path.join(dest_dir, candidate)
    i = 1
    while os.path.exists(full):
        candidate = f"{base_name}-{i}{ext}"
        full = os.path.join(dest_dir, candidate)
        i += 1
    return full

# ---------- Main logic ----------
def process_file(exiftool_path, filepath, dest_dir, do_copy=False, dry_run=True):
    """Process one file: extract metadata, build new filename, and rename/copy if not dry_run."""
    exif = run_exiftool_json(exiftool_path, filepath) or {}
    ts_str, _ = format_timestamp_from_exif(exif)
    if not ts_str:
        ts_str, _ = get_fallback_mtime(filepath)

    latlon = format_latlon(exif)
    # original base name (without extension)
    orig_base = os.path.splitext(os.path.basename(filepath))[0]
    orig_base_safe = safe_filename(orig_base)

    parts = [ts_str]
    if latlon:
        parts.append(latlon)
    parts.append(orig_base_safe)
    base_name = "_".join(parts)
    # keep original extension lowercase
    ext = os.path.splitext(filepath)[1].lower() or ""
    # ensure extension exists (if none, keep empty)
    target_path = unique_target_path(dest_dir, base_name, ext)

    action = "COPY" if do_copy else "RENAME"
    if dry_run:
        print(f"[DRY] {action}: '{filepath}' -> '{target_path}'")
    else:
        print(f"{action}: '{filepath}' -> '{target_path}'")
        try:
            if do_copy:
                shutil.copy2(filepath, target_path)
            else:
                os.rename(filepath, target_path)
        except Exception as e:
            print(f"ERROR moving/copying {filepath} -> {target_path}: {e}", file=sys.stderr)

def collect_image_files(root, recursive=False):
    exts = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff", ".gif", ".bmp", ".webp"}
    files = []
    if recursive:
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in exts:
                    files.append(os.path.join(dirpath, fn))
    else:
        for fn in os.listdir(root):
            p = os.path.join(root, fn)
            if os.path.isfile(p) and os.path.splitext(fn)[1].lower() in exts:
                files.append(p)
    files.sort()
    return files

def main():
    parser = argparse.ArgumentParser(description="Rename images by EXIF date/time (+subseconds) and GPS.")
    parser.add_argument("folder", help="Folder with images to process")
    parser.add_argument("--recursive", "-r", action="store_true", help="Process files recursively")
    parser.add_argument("--dry-run", "-n", action="store_true", default=True,
                        help="Show what would be done without renaming (default ON). Use --no-dry-run to actually rename.")
    parser.add_argument("--no-dry-run", dest='dry_run', action='store_false', help="Actually perform renames")
    parser.add_argument("--copy", action="store_true", help="Copy files with new names instead of renaming originals")
    parser.add_argument("--dest", "-d", default=None, help="Destination directory (default: same folder as file)")
    args = parser.parse_args()

    try:
        exiftool_path = check_exiftool()
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    folder = args.folder
    if not os.path.exists(folder):
        print(f"Folder not found: {folder}", file=sys.stderr)
        sys.exit(1)
    files = collect_image_files(folder, recursive=args.recursive)
    if not files:
        print("No image files found.", file=sys.stderr)
        sys.exit(0)

    for f in files:
        dest_dir = args.dest if args.dest else os.path.dirname(f)
        process_file(exiftool_path, f, dest_dir, do_copy=args.copy, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
