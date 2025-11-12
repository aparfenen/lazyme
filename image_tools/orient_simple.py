#!/usr/bin/env python3
"""
Simple Image Orientation Fixer
Just works - no complications!
"""

import sys
import os
from pathlib import Path
from PIL import Image, ImageOps

# Enable HEIC support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    print("✓ HEIC support enabled")
except ImportError:
    print("⚠️  No HEIC support - install pillow-heif")

def fix_image(filepath):
    """Fix a single image orientation."""
    try:
        # Open image
        img = Image.open(filepath)
        
        # Get EXIF orientation
        exif = img.getexif()
        orientation = exif.get(0x0112, 1) if exif else 1
        
        # Skip if already correct
        if orientation == 1:
            img.close()
            return False, "already correct"
        
        # Apply rotation
        rotated = ImageOps.exif_transpose(img)
        if rotated is None or rotated == img:
            img.close()
            return False, "no change needed"
        
        # Save with reset orientation
        if exif:
            exif[0x0112] = 1
        
        # Determine output format
        ext = filepath.suffix.lower()
        if ext in ['.heic', '.heif']:
            # Convert HEIC to JPEG
            output_path = filepath.with_suffix('.jpg')
            format_type = 'JPEG'
        elif ext == '.dng':
            # Convert DNG to JPEG (DNG is read-only in PIL)
            output_path = filepath.with_suffix('.jpg')
            format_type = 'JPEG'
        else:
            output_path = filepath
            format_type = None
        
        # Save
        save_kwargs = {}
        if exif:
            save_kwargs['exif'] = exif.tobytes()
        if 'icc_profile' in img.info:
            save_kwargs['icc_profile'] = img.info['icc_profile']
        if format_type == 'JPEG' or ext in ['.jpg', '.jpeg']:
            save_kwargs['quality'] = 95
            save_kwargs['optimize'] = True
        
        if format_type:
            rotated.save(output_path, format_type, **save_kwargs)
        else:
            rotated.save(output_path, **save_kwargs)
        
        # Report sizes
        orig_size = f"{img.size[0]}x{img.size[1]}"
        new_size = f"{rotated.size[0]}x{rotated.size[1]}"
        
        # Add conversion note if format changed
        if output_path != filepath:
            conversion = f" (saved as {output_path.name})"
        else:
            conversion = ""
        
        img.close()
        rotated.close()
        
        return True, f"rotated {orig_size} → {new_size}{conversion}"
        
    except Exception as e:
        return False, str(e)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 orient_simple.py <directory_or_file> [--dry-run]")
        sys.exit(1)
    
    path = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv
    
    if not path.exists():
        print(f"Error: {path} not found")
        sys.exit(1)
    
    # Collect image files
    extensions = {'.heic', '.heif', '.jpg', '.jpeg', '.png', '.dng', '.tiff', '.bmp'}
    
    if path.is_file():
        files = [path] if path.suffix.lower() in extensions else []
    else:
        files = []
        for ext in extensions:
            files.extend(path.glob(f'*{ext}'))
            files.extend(path.glob(f'*{ext.upper()}'))
    
    if not files:
        print("No image files found")
        return
    
    print(f"Found {len(files)} image files")
    if dry_run:
        print("DRY RUN MODE - no changes will be made\n")
    else:
        print("Processing...\n")
    
    # Process files
    fixed = 0
    skipped = 0
    errors = 0
    
    for filepath in sorted(files):
        if dry_run:
            # Quick check without modifying
            try:
                img = Image.open(filepath)
                exif = img.getexif()
                orientation = exif.get(0x0112, 1) if exif else 1
                img.close()
                
                if orientation != 1:
                    print(f"[DRY] Would fix: {filepath.name} (orientation={orientation})")
                    fixed += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"[DRY] Error: {filepath.name} - {e}")
                errors += 1
        else:
            # Actually fix the file
            success, message = fix_image(filepath)
            if success:
                print(f"✓ Fixed: {filepath.name} - {message}")
                fixed += 1
            elif "already correct" in message or "no change" in message:
                skipped += 1
            else:
                print(f"✗ Error: {filepath.name} - {message}")
                errors += 1
    
    # Summary
    print(f"\n{'='*50}")
    print(f"Results:")
    print(f"  Fixed:   {fixed}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors:  {errors}")
    print(f"  Total:   {len(files)}")
    
    if dry_run and fixed > 0:
        print(f"\nRun without --dry-run to apply changes")

if __name__ == '__main__':
    main()
