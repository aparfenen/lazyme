#!/usr/bin/env python3
"""
Diagnostic script to check EXIF orientation tags in image files.
This will help understand why files are being skipped.
"""

import sys
from pathlib import Path
from collections import Counter
from PIL import Image, ExifTags

# Try to load HEIF support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HAS_HEIF = True
except ImportError:
    HAS_HEIF = False
    print("Warning: pillow-heif not installed. HEIC files won't be processed.")

def get_orientation_tag(img):
    """Get EXIF orientation tag value."""
    try:
        exif = img.getexif()
        if exif:
            # Try numeric tag first
            orientation = exif.get(0x0112, None)
            if orientation:
                return orientation
            
            # Try by tag name
            for tag, value in exif.items():
                if tag in ExifTags.TAGS and ExifTags.TAGS[tag] == 'Orientation':
                    return value
    except Exception:
        pass
    return 1  # Default

def orientation_to_description(orientation):
    """Convert orientation number to description."""
    descriptions = {
        1: "Normal (no rotation needed)",
        2: "Mirrored horizontally",
        3: "Rotated 180°",
        4: "Mirrored vertically", 
        5: "Mirrored horizontally and rotated 270° CW",
        6: "Rotated 90° CW (270° CCW)",
        7: "Mirrored horizontally and rotated 90° CW",
        8: "Rotated 270° CW (90° CCW)"
    }
    return descriptions.get(orientation, f"Unknown ({orientation})")

def analyze_directory(path):
    """Analyze all images in directory."""
    path = Path(path)
    
    if not path.exists():
        print(f"Path not found: {path}")
        sys.exit(1)
    
    # Collect all image files
    extensions = {'.heic', '.heif', '.jpg', '.jpeg', '.png', '.tif', '.tiff', 
                  '.gif', '.webp', '.bmp', '.dng', '.cr2', '.nef', '.arw'}
    
    if path.is_file():
        files = [path] if path.suffix.lower() in extensions else []
    else:
        files = [f for f in path.rglob('*') if f.suffix.lower() in extensions]
    
    if not files:
        print("No image files found.")
        return
    
    print(f"Analyzing {len(files)} image files...\n")
    
    # Statistics
    orientation_stats = Counter()
    format_stats = Counter()
    needs_rotation = []
    errors = []
    
    # Analyze each file
    for filepath in sorted(files):
        try:
            ext = filepath.suffix.lower()
            format_stats[ext] += 1
            
            img = Image.open(filepath)
            orientation = get_orientation_tag(img)
            orientation_stats[orientation] += 1
            
            if orientation != 1:
                w, h = img.size
                is_landscape = w >= h
                needs_rotation.append({
                    'file': filepath.name,
                    'orientation': orientation,
                    'size': f"{w}x{h}",
                    'type': 'L' if is_landscape else 'P'
                })
            
            img.close()
            
        except Exception as e:
            if 'cannot identify image file' in str(e):
                if ext in {'.heic', '.heif'}:
                    errors.append(f"{filepath.name}: HEIC file (need pillow-heif)")
                else:
                    errors.append(f"{filepath.name}: Cannot read file")
            else:
                errors.append(f"{filepath.name}: {e}")
    
    # Print results
    print("=" * 60)
    print("FILE FORMAT DISTRIBUTION:")
    print("=" * 60)
    for ext, count in sorted(format_stats.items()):
        print(f"  {ext:8} : {count:4} files")
    print()
    
    print("=" * 60)
    print("ORIENTATION TAG DISTRIBUTION:")
    print("=" * 60)
    for orientation, count in sorted(orientation_stats.items()):
        desc = orientation_to_description(orientation)
        print(f"  Tag {orientation}: {count:4} files - {desc}")
    print()
    
    if needs_rotation:
        print("=" * 60)
        print(f"FILES NEEDING ROTATION ({len(needs_rotation)} files):")
        print("=" * 60)
        for item in needs_rotation[:20]:  # Show first 20
            print(f"  {item['file']:30} | Tag {item['orientation']} | {item['type']} {item['size']}")
        if len(needs_rotation) > 20:
            print(f"  ... and {len(needs_rotation) - 20} more files")
        print()
    
    if errors:
        print("=" * 60)
        print(f"ERRORS ({len(errors)} files):")
        print("=" * 60)
        for error in errors[:10]:
            print(f"  {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more errors")
        print()
    
    # Summary
    print("=" * 60)
    print("SUMMARY:")
    print("=" * 60)
    print(f"  Total files analyzed:    {len(files)}")
    print(f"  Files needing rotation:  {len(needs_rotation)}")
    print(f"  Files already correct:   {orientation_stats.get(1, 0)}")
    print(f"  Files with errors:       {len(errors)}")
    print()
    
    if needs_rotation:
        print("To fix these files, run:")
        print(f"  python3 orient_pro.py {path} --mode exif --no-dry-run")

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 check_orientations.py <directory>")
        sys.exit(1)
    
    analyze_directory(sys.argv[1])
