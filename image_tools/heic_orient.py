#!/usr/bin/env python3
"""
HEIC Auto-Orient Script
Specialized for iPhone HEIC files with better metadata handling.
"""

import argparse
import sys
from pathlib import Path
from PIL import Image, ImageOps

# Required for HEIC
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HAS_HEIF = True
except ImportError:
    print("ERROR: pillow-heif is required for HEIC files!")
    print("Install it with: pip install pillow-heif")
    sys.exit(1)

def process_heic_file(filepath, output_dir=None, dry_run=True, convert_to_jpeg=False):
    """Process a single HEIC file."""
    filepath = Path(filepath)
    
    try:
        # Open the image
        img = Image.open(filepath)
        
        # Get original orientation
        exif = img.getexif()
        orientation = exif.get(0x0112, 1) if exif else 1
        
        # Check if rotation is needed
        if orientation == 1:
            img.close()
            return False, "Already correctly oriented"
        
        # Apply EXIF orientation
        rotated = ImageOps.exif_transpose(img)
        if rotated is None:
            img.close()
            return False, "No rotation needed"
        
        # Determine output path
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            if convert_to_jpeg:
                output_path = output_dir / filepath.with_suffix('.jpg').name
            else:
                output_path = output_dir / filepath.name
        else:
            if convert_to_jpeg:
                output_path = filepath.with_suffix('.jpg')
            else:
                output_path = filepath
        
        if dry_run:
            action = "Would rotate"
            if convert_to_jpeg:
                action += " and convert to JPEG"
            print(f"[DRY RUN] {action}: {filepath.name} → {output_path.name}")
        else:
            # Save with corrected orientation
            save_kwargs = {
                'quality': 95,
                'optimize': True
            }
            
            # Reset orientation in EXIF
            if exif:
                exif[0x0112] = 1
                save_kwargs['exif'] = exif.tobytes()
            
            # Preserve ICC profile
            if 'icc_profile' in img.info:
                save_kwargs['icc_profile'] = img.info['icc_profile']
            
            # Save the file
            if convert_to_jpeg or output_path.suffix.lower() in ['.jpg', '.jpeg']:
                rotated.save(output_path, 'JPEG', **save_kwargs)
            else:
                # Try to save as HEIF, fallback to JPEG if fails
                try:
                    rotated.save(output_path, 'HEIF', **save_kwargs)
                except:
                    # Fallback to JPEG
                    output_path = output_path.with_suffix('.jpg')
                    rotated.save(output_path, 'JPEG', **save_kwargs)
            
            print(f"✓ Rotated: {filepath.name} → {output_path.name}")
        
        img.close()
        rotated.close()
        return True, None
        
    except Exception as e:
        return False, str(e)

def main():
    parser = argparse.ArgumentParser(
        description="Auto-orient HEIC files from iPhone",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check which files need rotation (dry run)
  python3 heic_orient.py ~/Documents/imgs
  
  # Apply rotation in-place
  python3 heic_orient.py ~/Documents/imgs --no-dry-run
  
  # Convert to JPEG while rotating
  python3 heic_orient.py ~/Documents/imgs --convert-to-jpeg --no-dry-run
  
  # Save to different directory
  python3 heic_orient.py ~/Documents/imgs --output ~/Documents/imgs_fixed --no-dry-run
        """
    )
    
    parser.add_argument('path', type=Path, help="File or directory to process")
    parser.add_argument('--output', '-o', type=Path, help="Output directory")
    parser.add_argument('--convert-to-jpeg', '-j', action='store_true', 
                       help="Convert HEIC to JPEG while processing")
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help="Preview changes without modifying (default)")
    parser.add_argument('--no-dry-run', dest='dry_run', action='store_false',
                       help="Actually modify files")
    parser.add_argument('--recursive', '-r', action='store_true', default=True,
                       help="Process directories recursively (default)")
    
    args = parser.parse_args()
    
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}")
        sys.exit(1)
    
    # Collect HEIC files
    if args.path.is_file():
        if args.path.suffix.lower() in ['.heic', '.heif']:
            files = [args.path]
        else:
            print(f"Error: Not a HEIC file: {args.path}")
            sys.exit(1)
    else:
        pattern = '**/*' if args.recursive else '*'
        files = list(args.path.glob(pattern))
        files = [f for f in files if f.is_file() and f.suffix.lower() in ['.heic', '.heif']]
    
    if not files:
        print("No HEIC files found.")
        sys.exit(0)
    
    print(f"Found {len(files)} HEIC file(s)")
    
    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No files will be modified")
        print("Use --no-dry-run to actually process files\n")
    
    # Process files
    processed = 0
    skipped = 0
    errors = 0
    
    for filepath in sorted(files):
        success, error = process_heic_file(
            filepath, 
            args.output, 
            args.dry_run,
            args.convert_to_jpeg
        )
        
        if success:
            processed += 1
        elif error:
            if "Already correctly oriented" in error:
                skipped += 1
            else:
                errors += 1
                print(f"Error: {filepath.name}: {error}")
        else:
            skipped += 1
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"{'='*60}")
    print(f"  Files processed: {processed}")
    print(f"  Files skipped:   {skipped}")
    print(f"  Errors:          {errors}")
    print(f"  Total:           {len(files)}")
    
    if args.output and not args.dry_run:
        print(f"\nOutput directory: {args.output}")

if __name__ == '__main__':
    main()
