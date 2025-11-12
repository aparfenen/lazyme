#!/usr/bin/env python3
"""
orient_pro.py - Professional Image Orientation Tool (Optimized Version)

Two powerful orientation modes:
  1) exif   - Apply EXIF Orientation tag and reset to normal (1)
  2) target - Force all images to landscape or portrait orientation

Key improvements:
  - Faster detection of images needing rotation
  - Better HEIC/HEIF handling with fallback methods
  - Optimized for dry-run performance
  - More accurate orientation detection
  
Author: Professional Image Processing Suite
Version: 2.1
"""

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
import time

from PIL import Image, ImageOps, ExifTags

# Optional HEIF support
HEIF_SUPPORT = False
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_SUPPORT = True
except ImportError:
    # Try alternative method for HEIC
    try:
        import pyheif
        from PIL import Image
        import io
        
        def open_heic(filepath):
            """Open HEIC file using pyheif."""
            heif_file = pyheif.read(filepath)
            img = Image.open(io.BytesIO(heif_file.data))
            # Transfer EXIF data if available
            for metadata in heif_file.metadata or []:
                if metadata['type'] == 'Exif':
                    img.info['exif'] = metadata['data']
            return img
        
        HEIF_SUPPORT = "pyheif"
    except ImportError:
        pass

# Optional progress bar
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


# ============================================================================
# Configuration
# ============================================================================

SUPPORTED_EXTENSIONS = {
    '.heic', '.heif',  # Apple HEIF
    '.jpg', '.jpeg',   # JPEG
    '.png',            # PNG
    '.tif', '.tiff',   # TIFF
    '.gif',            # GIF
    '.webp',           # WebP
    '.bmp',            # BMP
    '.dng',            # Adobe DNG
}

# Format mapping for PIL save
FORMAT_MAP = {
    '.jpg': 'JPEG',
    '.jpeg': 'JPEG',
    '.png': 'PNG',
    '.tif': 'TIFF',
    '.tiff': 'TIFF',
    '.heic': 'JPEG',  # Convert HEIC to JPEG for better compatibility
    '.heif': 'JPEG',  # Convert HEIF to JPEG
    '.gif': 'GIF',
    '.webp': 'WEBP',
    '.bmp': 'BMP',
}

# JPEG quality settings
JPEG_QUALITY = 95
JPEG_SUBSAMPLING = 2  # Use 2 for better compatibility


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ProcessingStats:
    """Track processing statistics."""
    total: int = 0
    processed: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: List[str] = None
    
    def __post_init__(self):
        if self.error_details is None:
            self.error_details = []
    
    def add_error(self, filepath: str, error: str):
        """Add error to tracking."""
        self.errors += 1
        self.error_details.append(f"{filepath}: {error}")
    
    def __str__(self) -> str:
        return (
            f"\n{'='*60}\n"
            f"Processing Statistics:\n"
            f"{'='*60}\n"
            f"Total files:          {self.total}\n"
            f"Successfully oriented: {self.processed}\n"
            f"Skipped (no change):  {self.skipped}\n"
            f"Errors:               {self.errors}\n"
            f"{'='*60}"
        )


# ============================================================================
# Image File Discovery
# ============================================================================

def iter_images(path: Path, recursive: bool = True) -> Iterable[Path]:
    """
    Iterate over image files in a directory or return single file.
    """
    if path.is_file():
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path
        return
    
    if not path.is_dir():
        return
    
    pattern = "**/*" if recursive else "*"
    for item in path.glob(pattern):
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield item


def is_icloud_placeholder(filepath: Path) -> bool:
    """
    Detect if file is an iCloud placeholder (not downloaded).
    """
    try:
        size = filepath.stat().st_size
        # Typical placeholders are < 50KB for HEIC files
        # Real HEIC images are usually > 500KB
        if filepath.suffix.lower() in {'.heic', '.heif'}:
            return size < 50000
        # For other formats
        return size < 10000
    except OSError:
        pass
    return False


# ============================================================================
# EXIF Metadata Handling
# ============================================================================

def get_orientation_tag(img: Image.Image) -> int:
    """
    Get EXIF Orientation tag value with multiple fallback methods.
    """
    try:
        # Method 1: Direct EXIF access
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
    
    try:
        # Method 2: Check _getexif for older PIL versions
        if hasattr(img, '_getexif'):
            exif = img._getexif()
            if exif:
                return exif.get(274, 1)  # 274 is orientation tag
    except Exception:
        pass
    
    try:
        # Method 3: Check info dict
        if 'exif' in img.info:
            from PIL.ExifTags import TAGS
            exif = img.getexif()
            for tag, value in exif.items():
                if TAGS.get(tag) == 'Orientation':
                    return value
    except Exception:
        pass
    
    return 1  # Default to normal orientation


def needs_orientation_fix(img: Image.Image) -> bool:
    """
    Check if image needs orientation correction based on EXIF.
    More comprehensive check including image dimensions.
    """
    orientation = get_orientation_tag(img)
    
    # Orientation values that need correction:
    # 1: Normal (no correction needed)
    # 2: Mirrored horizontally
    # 3: Rotated 180
    # 4: Mirrored vertically
    # 5: Mirrored horizontally and rotated 270 CW
    # 6: Rotated 90 CW
    # 7: Mirrored horizontally and rotated 90 CW
    # 8: Rotated 270 CW (90 CCW)
    
    return orientation != 1


def apply_exif_orientation(img: Image.Image) -> Tuple[Image.Image, bool]:
    """
    Apply EXIF Orientation and return rotated image.
    Enhanced with multiple methods and better error handling.
    """
    orientation = get_orientation_tag(img)
    
    if orientation == 1:
        return img, False
    
    try:
        # Method 1: Use ImageOps.exif_transpose (best method)
        rotated = ImageOps.exif_transpose(img)
        if rotated is not None and rotated != img:
            return rotated, True
    except Exception as e:
        logging.debug(f"ImageOps.exif_transpose failed: {e}")
    
    try:
        # Method 2: Manual rotation based on orientation value
        if orientation == 2:  # Flipped horizontally
            return img.transpose(Image.FLIP_LEFT_RIGHT), True
        elif orientation == 3:  # Rotated 180
            return img.rotate(180, expand=True), True
        elif orientation == 4:  # Flipped vertically
            return img.transpose(Image.FLIP_TOP_BOTTOM), True
        elif orientation == 5:  # Flipped horizontally and rotated 270 CW
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
            return img.rotate(270, expand=True), True
        elif orientation == 6:  # Rotated 90 CW (270 CCW)
            return img.rotate(270, expand=True), True
        elif orientation == 7:  # Flipped horizontally and rotated 90 CW
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
            return img.rotate(90, expand=True), True
        elif orientation == 8:  # Rotated 270 CW (90 CCW)
            return img.rotate(90, expand=True), True
    except Exception as e:
        logging.debug(f"Manual rotation failed: {e}")
    
    return img, False


def force_orientation(img: Image.Image, want_landscape: bool) -> Tuple[Image.Image, bool]:
    """
    Force image to be landscape or portrait.
    """
    width, height = img.size
    is_landscape = width >= height
    
    # Already in desired orientation
    if is_landscape == want_landscape:
        return img, False
    
    # Rotate 90 degrees to switch orientation
    # Use rotate with expand=True to adjust canvas size
    rotated = img.rotate(270 if want_landscape else 90, expand=True)
    return rotated, True


# ============================================================================
# Image Opening with HEIC support
# ============================================================================

def open_image_safe(filepath: Path) -> Optional[Image.Image]:
    """
    Open image with multiple fallback methods for HEIC files.
    """
    try:
        # Standard PIL open
        return Image.open(filepath)
    except Exception as e:
        if filepath.suffix.lower() in {'.heic', '.heif'}:
            # Try alternative HEIC opening methods
            if HEIF_SUPPORT == "pyheif":
                try:
                    return open_heic(filepath)
                except Exception:
                    pass
            
            # If all else fails, we might need to convert using system tools
            logging.warning(f"Cannot open HEIC file {filepath}: {e}")
            logging.warning("Install pillow-heif for HEIC support: pip install pillow-heif")
        return None


# ============================================================================
# Image Saving with Metadata Preservation
# ============================================================================

def save_with_metadata(
    img: Image.Image, 
    output_path: Path, 
    source_path: Path,
    reset_orientation: bool = True
) -> None:
    """
    Save image with maximum metadata preservation.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    ext = source_path.suffix.lower()
    fmt = FORMAT_MAP.get(ext, 'JPEG')
    
    # For HEIC, change extension to JPEG
    if ext in {'.heic', '.heif'}:
        output_path = output_path.with_suffix('.jpg')
    
    save_kwargs = {}
    
    try:
        # Preserve EXIF data but reset orientation
        exif = img.getexif()
        if exif and reset_orientation:
            # Reset orientation to 1 (normal)
            exif[0x0112] = 1
            save_kwargs['exif'] = exif.tobytes()
    except Exception as e:
        logging.debug(f"Could not process EXIF: {e}")
    
    # Preserve ICC profile
    if 'icc_profile' in img.info:
        save_kwargs['icc_profile'] = img.info['icc_profile']
    
    # JPEG-specific settings
    if fmt == 'JPEG':
        save_kwargs['quality'] = JPEG_QUALITY
        save_kwargs['subsampling'] = JPEG_SUBSAMPLING
        save_kwargs['optimize'] = True
    
    # Save the image
    if fmt:
        img.save(output_path, format=fmt, **save_kwargs)
    else:
        img.save(output_path, **save_kwargs)


# ============================================================================
# Core Processing Functions
# ============================================================================

def process_single_image(
    filepath: Path,
    mode: str,
    target_orientation: Optional[str],
    inplace: bool,
    output_dir: Optional[Path],
    base_dir: Path,
    dry_run: bool
) -> Tuple[bool, Optional[str]]:
    """
    Process a single image file.
    Returns (success, error_message)
    """
    # Skip iCloud placeholders
    if is_icloud_placeholder(filepath):
        return False, "iCloud placeholder (not downloaded)"
    
    try:
        # Open image with fallback methods
        img = open_image_safe(filepath)
        if img is None:
            return False, "Cannot open image (install pillow-heif for HEIC support)"
        
        original_size = img.size
        
        # Apply transformation based on mode
        if mode == 'exif':
            result_img, changed = apply_exif_orientation(img)
            action_desc = "EXIF rotation applied"
        else:  # target mode
            want_landscape = (target_orientation == 'landscape')
            result_img, changed = force_orientation(img, want_landscape)
            action_desc = f"Forced to {target_orientation}"
        
        if not changed:
            img.close()
            return False, None  # No change needed
        
        # Prepare output path
        if inplace:
            output_path = filepath
        else:
            rel_path = filepath.relative_to(base_dir) if base_dir in filepath.parents else filepath.name
            output_path = output_dir / rel_path
        
        # Format orientation info for display
        def orientation_str(size):
            w, h = size
            return 'L' if w >= h else 'P'
        
        orig_orient = orientation_str(original_size)
        new_orient = orientation_str(result_img.size)
        size_info = f"{orig_orient} {original_size[0]}x{original_size[1]} → {new_orient} {result_img.size[0]}x{result_img.size[1]}"
        
        if dry_run:
            print(f"[DRY RUN] {action_desc}: {filepath.name} ({size_info})")
        else:
            save_with_metadata(result_img, output_path, filepath)
            print(f"✓ {action_desc}: {filepath.name} ({size_info})")
        
        img.close()
        result_img.close()
        return True, None
        
    except Exception as e:
        error_msg = str(e)
        if "cannot identify image file" in error_msg.lower():
            if filepath.suffix.lower() in {'.heic', '.heif'}:
                return False, "HEIC file - install pillow-heif: pip install pillow-heif"
        return False, error_msg


def process_images_batch(
    files: List[Path],
    mode: str,
    target_orientation: Optional[str] = None,
    inplace: bool = False,
    output_dir: Optional[Path] = None,
    base_dir: Optional[Path] = None,
    dry_run: bool = True,
    max_workers: int = 1
) -> ProcessingStats:
    """
    Process multiple images with optional parallel processing.
    """
    stats = ProcessingStats(total=len(files))
    
    # For dry-run, check first few files to see if we need pillow-heif
    heic_count = sum(1 for f in files if f.suffix.lower() in {'.heic', '.heif'})
    if heic_count > 0 and not HEIF_SUPPORT:
        print(f"\n⚠️  Found {heic_count} HEIC/HEIF files but pillow-heif is not installed.")
        print("   Install it for HEIC support: pip install pillow-heif")
        print("   Continuing with other formats...\n")
    
    # Setup progress bar
    progress = None
    if HAS_TQDM:
        progress = tqdm(total=len(files), desc="Processing images", unit="img")
    
    try:
        if max_workers > 1 and not dry_run:  # Only use parallel for actual processing
            # Parallel processing
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        process_single_image,
                        path, mode, target_orientation, inplace,
                        output_dir, base_dir, dry_run
                    ): path
                    for path in files
                }
                
                for future in as_completed(futures):
                    path = futures[future]
                    try:
                        success, error = future.result()
                        if error:
                            stats.add_error(str(path), error)
                        elif success:
                            stats.processed += 1
                        else:
                            stats.skipped += 1
                    except Exception as e:
                        stats.add_error(str(path), f"Processing failed: {e}")
                    
                    if progress:
                        progress.update(1)
        else:
            # Sequential processing (faster for dry-run)
            for path in files:
                success, error = process_single_image(
                    path, mode, target_orientation, inplace,
                    output_dir, base_dir, dry_run
                )
                
                if error:
                    if "HEIC file" not in error and "iCloud placeholder" not in error:
                        stats.add_error(str(path), error)
                    else:
                        stats.skipped += 1
                elif success:
                    stats.processed += 1
                else:
                    stats.skipped += 1
                
                if progress:
                    progress.update(1)
    
    finally:
        if progress:
            progress.close()
    
    return stats


# ============================================================================
# CLI Interface
# ============================================================================

def setup_logging(verbose: bool) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(levelname)s: %(message)s'
    )


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Professional image orientation tool with EXIF handling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Apply EXIF orientation (dry run)
  python3 %(prog)s /path/to/photos --mode exif
  
  # Apply EXIF orientation (actual)
  python3 %(prog)s /path/to/photos --mode exif --no-dry-run
  
  # Force all to landscape
  python3 %(prog)s /path/to/photos --mode target --target landscape --no-dry-run
  
  # Process with parallel workers
  python3 %(prog)s /path/to/photos --mode exif --workers 4 --no-dry-run

Notes:
  - For HEIC/HEIF support: pip install pillow-heif
  - Mode 'exif': Applies EXIF Orientation tag, then resets it to 1
  - Mode 'target': Forces specific orientation regardless of EXIF
        """
    )
    
    parser.add_argument(
        'path',
        type=Path,
        help="File or directory to process"
    )
    
    parser.add_argument(
        '--mode',
        choices=['exif', 'target'],
        required=True,
        help="Processing mode"
    )
    
    parser.add_argument(
        '--target',
        choices=['landscape', 'portrait'],
        help="Target orientation for --mode target"
    )
    
    parser.add_argument(
        '--inplace',
        action='store_true',
        help="Modify files in place"
    )
    
    parser.add_argument(
        '--out',
        type=Path,
        help="Output directory"
    )
    
    parser.add_argument(
        '-r', '--recursive',
        dest='recursive',
        action='store_true',
        default=True,
        help="Process directories recursively (default)"
    )
    
    parser.add_argument(
        '--no-recursive',
        dest='recursive',
        action='store_false',
        help="Don't process recursively"
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help="Preview changes (default)"
    )
    
    parser.add_argument(
        '--no-dry-run',
        dest='dry_run',
        action='store_false',
        help="Actually modify files"
    )
    
    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        help="Parallel workers (default: 1)"
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help="Verbose output"
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_arguments()
    
    # Setup logging
    setup_logging(args.verbose)
    
    # Validate arguments
    if args.mode == 'target' and not args.target:
        print("Error: --target is required when using --mode target", file=sys.stderr)
        sys.exit(1)
    
    if args.inplace and args.out:
        print("Error: Cannot use both --inplace and --out", file=sys.stderr)
        sys.exit(1)
    
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)
    
    # Determine output directory
    if args.inplace:
        output_dir = None
    elif args.out:
        output_dir = args.out
    else:
        base = args.path
        output_dir = base.parent / f"{base.name}_oriented"
    
    # Collect files
    print(f"Scanning for images in {args.path}...")
    start_time = time.time()
    files = list(iter_images(args.path, args.recursive))
    
    if not files:
        print("No image files found.", file=sys.stderr)
        sys.exit(0)
    
    print(f"Found {len(files)} image file(s) in {time.time() - start_time:.1f}s")
    
    # Show mode info
    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No files will be modified")
        print("Use --no-dry-run to actually process files\n")
    
    mode_desc = {
        'exif': "Applying EXIF Orientation",
        'target': f"Forcing to {args.target}"
    }
    print(f"Mode: {mode_desc.get(args.mode, args.mode)}\n")
    
    # Process files
    base_dir = args.path if args.path.is_dir() else args.path.parent
    
    process_start = time.time()
    stats = process_images_batch(
        files=files,
        mode=args.mode,
        target_orientation=args.target,
        inplace=args.inplace,
        output_dir=output_dir,
        base_dir=base_dir,
        dry_run=args.dry_run,
        max_workers=args.workers if not args.dry_run else 1
    )
    process_time = time.time() - process_start
    
    # Print results
    print(stats)
    print(f"Processing time: {process_time:.1f}s")
    
    if stats.errors > 0 and args.verbose:
        print("\nErrors encountered:")
        for error in stats.error_details[:10]:
            print(f"  • {error}")
        if len(stats.error_details) > 10:
            print(f"  ... and {len(stats.error_details) - 10} more errors")
    
    if not args.inplace and output_dir and not args.dry_run:
        print(f"\n✓ Output directory: {output_dir}")
    
    sys.exit(0 if stats.errors == 0 else 1)


if __name__ == '__main__':
    main()
