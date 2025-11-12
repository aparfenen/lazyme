#!/usr/bin/env python3
"""
Universal Image Orientation Fixer
Handles all formats including DNG, with smart conversion options
"""

import sys
import os
from pathlib import Path
from PIL import Image, ImageOps
import shutil

# Enable HEIC support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False

def fix_image(filepath, convert_to_jpeg=False, output_dir=None):
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
        
        # Reset orientation tag
        if exif:
            exif[0x0112] = 1
        
        # Determine output path and format
        ext = filepath.suffix.lower()
        
        # Set output directory
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            base_output = output_dir / filepath.name
        else:
            base_output = filepath
        
        # Handle format conversion
        if convert_to_jpeg or ext in ['.dng', '.heic', '.heif']:
            # These formats need conversion to JPEG
            output_path = base_output.with_suffix('.jpg')
            format_type = 'JPEG'
            converted = True
        elif ext in ['.tiff', '.tif']:
            # Keep as TIFF
            output_path = base_output
            format_type = 'TIFF'
            converted = False
        elif ext == '.png':
            # Keep as PNG
            output_path = base_output
            format_type = 'PNG'
            converted = False
        elif ext in ['.jpg', '.jpeg']:
            # Keep as JPEG
            output_path = base_output
            format_type = 'JPEG'
            converted = False
        else:
            # Default to original format
            output_path = base_output
            format_type = None
            converted = False
        
        # Prepare save parameters
        save_kwargs = {}
        
        # Add EXIF data
        if exif:
            save_kwargs['exif'] = exif.tobytes()
        
        # Preserve ICC profile
        if 'icc_profile' in img.info:
            save_kwargs['icc_profile'] = img.info['icc_profile']
        
        # Format-specific options
        if format_type == 'JPEG':
            save_kwargs['quality'] = 95
            save_kwargs['optimize'] = True
        elif format_type == 'PNG':
            save_kwargs['compress_level'] = 6
        elif format_type == 'TIFF':
            save_kwargs['compression'] = 'tiff_lzw'
        
        # Save the rotated image
        if format_type:
            rotated.save(output_path, format_type, **save_kwargs)
        else:
            rotated.save(output_path, **save_kwargs)
        
        # Report results
        orig_size = f"{img.size[0]}x{img.size[1]}"
        new_size = f"{rotated.size[0]}x{rotated.size[1]}"
        
        result_msg = f"rotated {orig_size} → {new_size}"
        if converted:
            result_msg += f" (converted to {output_path.suffix})"
        if output_dir:
            result_msg += f" → {output_path.parent.name}/"
        
        img.close()
        rotated.close()
        
        return True, result_msg
        
    except Exception as e:
        return False, str(e)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Fix image orientation for all formats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check what needs fixing (dry run)
  python3 orient_all.py ~/Documents/imgs --dry-run
  
  # Fix orientation in place
  python3 orient_all.py ~/Documents/imgs
  
  # Convert DNG/HEIC to JPEG while fixing
  python3 orient_all.py ~/Documents/imgs --convert-to-jpeg
  
  # Save fixed images to new directory
  python3 orient_all.py ~/Documents/imgs --output ~/Documents/imgs_fixed
  
Note: DNG and HEIC files are automatically converted to JPEG
      unless they're already correctly oriented.
        """
    )
    
    parser.add_argument('path', type=Path, help="Directory or file to process")
    parser.add_argument('--dry-run', action='store_true', help="Preview without changes")
    parser.add_argument('--convert-to-jpeg', '-j', action='store_true', 
                       help="Convert all rotated images to JPEG")
    parser.add_argument('--output', '-o', type=Path, help="Output directory for fixed images")
    parser.add_argument('--recursive', '-r', action='store_true', default=False,
                       help="Process subdirectories")
    
    args = parser.parse_args()
    
    if not args.path.exists():
        print(f"Error: {args.path} not found")
        sys.exit(1)
    
    # Print status
    print(f"✓ HEIC support: {'enabled' if HEIC_SUPPORT else 'disabled (install pillow-heif)'}")
    
    # Collect image files
    extensions = {'.heic', '.heif', '.jpg', '.jpeg', '.png', '.dng', '.tiff', '.tif', '.bmp', '.gif', '.webp'}
    
    if args.path.is_file():
        files = [args.path] if args.path.suffix.lower() in extensions else []
    else:
        files = []
        if args.recursive:
            # Recursive search
            for ext in extensions:
                files.extend(args.path.rglob(f'*{ext}'))
                files.extend(args.path.rglob(f'*{ext.upper()}'))
        else:
            # Non-recursive search
            for ext in extensions:
                files.extend(args.path.glob(f'*{ext}'))
                files.extend(args.path.glob(f'*{ext.upper()}'))
    
    # Remove duplicates and sort
    files = sorted(set(files))
    
    if not files:
        print("No image files found")
        return
    
    print(f"Found {len(files)} image files")
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - no changes will be made\n")
    else:
        if args.output:
            print(f"Output directory: {args.output}")
        print("Processing...\n")
    
    # Count file types
    format_counts = {}
    for f in files:
        ext = f.suffix.lower()
        format_counts[ext] = format_counts.get(ext, 0) + 1
    
    print("File distribution:", ", ".join([f"{ext}: {count}" for ext, count in sorted(format_counts.items())]))
    print()
    
    # Process files
    fixed = 0
    skipped = 0
    errors = 0
    conversions = []
    
    for filepath in files:
        if args.dry_run:
            # Quick check without modifying
            try:
                img = Image.open(filepath)
                exif = img.getexif()
                orientation = exif.get(0x0112, 1) if exif else 1
                img.close()
                
                if orientation != 1:
                    ext = filepath.suffix.lower()
                    if ext in ['.dng', '.heic', '.heif']:
                        print(f"[DRY] Would fix & convert to JPEG: {filepath.name} (tag={orientation})")
                        conversions.append(filepath.name)
                    else:
                        print(f"[DRY] Would fix: {filepath.name} (tag={orientation})")
                    fixed += 1
                else:
                    skipped += 1
            except Exception as e:
                if not HEIC_SUPPORT and filepath.suffix.lower() in ['.heic', '.heif']:
                    print(f"[DRY] Cannot read: {filepath.name} (need pillow-heif)")
                else:
                    print(f"[DRY] Error: {filepath.name} - {e}")
                errors += 1
        else:
            # Actually fix the file
            success, message = fix_image(filepath, args.convert_to_jpeg, args.output)
            if success:
                print(f"✓ Fixed: {filepath.name} - {message}")
                fixed += 1
            elif "already correct" in message or "no change" in message:
                skipped += 1
            else:
                print(f"✗ Error: {filepath.name} - {message}")
                errors += 1
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"  Fixed:   {fixed}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors:  {errors}")
    print(f"  Total:   {len(files)}")
    
    if args.dry_run and fixed > 0:
        print(f"\n⚠️  {fixed} files need rotation")
        if conversions:
            print(f"   {len(conversions)} will be converted to JPEG (DNG/HEIC)")
        print(f"\nRun without --dry-run to apply changes")
    
    if not HEIC_SUPPORT and format_counts.get('.heic', 0) + format_counts.get('.heif', 0) > 0:
        print("\n💡 Tip: Install pillow-heif for HEIC support:")
        print("   pip install pillow-heif")

if __name__ == '__main__':
    main()
