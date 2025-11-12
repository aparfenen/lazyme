#!/usr/bin/env python3
"""
Two simple orientation tools in one script:

1) exif   — apply EXIF Orientation and reset it to 1.
2) target — force all images to landscape or portrait by rotating in {0,90,180,270}.

Supported: HEIC/HEIF, JPEG/JPG, PNG, TIFF, GIF, WEBP, BMP.
"""
import argparse, sys
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

import piexif

EXTS = {".heic",".heif",".jpg",".jpeg",".png",".tif",".tiff",".gif",".webp",".bmp"}
# NOTE: save HEIC as HEIF (pillow-heif expects "HEIF")
EXT2FMT = {
    ".jpg":"JPEG",".jpeg":"JPEG",".png":"PNG",".tif":"TIFF",".tiff":"TIFF",
    ".heic":"HEIF",".heif":"HEIF",".gif":"GIF",".webp":"WEBP",".bmp":"BMP"
}

def iter_images(p: Path, recursive: bool=True) -> Iterable[Path]:
    if p.is_file() and p.suffix.lower() in EXTS:
        yield p; return
    it = p.rglob("*") if recursive else p.glob("*")
    for q in it:
        if q.is_file() and q.suffix.lower() in EXTS:
            yield q

def exif_autorotate(im: Image.Image) -> Image.Image:
    return ImageOps.exif_transpose(im)

def force_target_rotation(im: Image.Image, want_landscape: bool) -> Image.Image:
    w, h = im.size
    is_landscape = w >= h
    if is_landscape == want_landscape:
        return im
    return im.rotate(90, expand=True)

def save_with_orientation_reset(src: Path, im: Image.Image, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    fmt = EXT2FMT.get(ext, None)

    exif_bytes = None
    try:
        exif = im.getexif()
        if exif:
            exif[0x0112] = 1  # Orientation
            exif_bytes = exif.tobytes()
    except Exception:
        exif_bytes = None

    save_kwargs = {}
    if exif_bytes and (fmt in ("JPEG","TIFF")):
        try:
            d = piexif.load(exif_bytes)
            d["0th"][piexif.ImageIFD.Orientation] = 1
            save_kwargs["exif"] = piexif.dump(d)
        except Exception:
            pass

    icc = im.info.get("icc_profile")
    if icc:
        save_kwargs["icc_profile"] = icc

    # JPEG: без subsampling="keep" (вызывает ошибки в Pillow 12), оставим quality=95
    if fmt == "JPEG":
        save_kwargs.setdefault("quality", 95)

    if fmt:
        im.save(dst, format=fmt, **save_kwargs)
    else:
        im.save(dst, **save_kwargs)

def main():
    ap = argparse.ArgumentParser(description="EXIF autorotate or force landscape/portrait.")
    ap.add_argument("path", type=Path, help="File or directory")
    ap.add_argument("--mode", choices=["exif","target"], required=True)
    ap.add_argument("--target", choices=["landscape","portrait"], help="Used when --mode target")
    ap.add_argument("--inplace", action="store_true", help="Modify files in place")
    ap.add_argument("--out", type=Path, help="Output directory (if not --inplace)")
    ap.add_argument("--no-recursive", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.mode == "target" and not args.target:
        ap.error("--target is required for --mode target")
    if args.inplace and args.out:
        ap.error("Use either --inplace or --out, not both.")
    if not args.path.exists():
        print(f"Path not found: {args.path}", file=sys.stderr); sys.exit(2)

    base = args.path
    recursive = not args.no_recursive
    out_dir = None if args.inplace else (args.out or (base.parent / f"{base.name}_oriented"))

    total = changed = 0
    for src in iter_images(base, recursive):
        total += 1
        try:
            with Image.open(src) as im:
                if args.mode == "exif":
                    out_im = exif_autorotate(im)
                    action = "exif"
                else:
                    want_landscape = (args.target == "landscape")
                    out_im = force_target_rotation(im, want_landscape)
                    action = f"target->{args.target}"

                if args.dry_run:
                    w,h = im.size; w2,h2 = out_im.size
                    bef = "L" if w>=h else "P"; aft = "L" if w2>=h2 else "P"
                    print(f"[>] {action}: {src.name} {bef}->{aft}")
                    changed += 1
                    continue

                dst = src if args.inplace else (out_dir / src.relative_to(base) if base.is_dir() else out_dir / src.name)
                save_with_orientation_reset(src, out_im, dst)
                changed += 1
        except OSError as e:
            print(f"[!] ERROR {src}: cannot open image ({e}). "
                  f"Возможные причины: iCloud placeholder не загружен, файл повреждён, или не-изображение.", file=sys.stderr)
        except ValueError as e:
            print(f"[!] ERROR {src}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[!] ERROR {src}: {e}", file=sys.stderr)

    print(f"Done. total={total}, processed={changed}")
    if not args.inplace and out_dir:
        print(f"Output: {out_dir}")

if __name__ == "__main__":
    main()
