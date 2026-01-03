#!/usr/bin/env python3
"""
remove_macos_duplicates.py

Remove macOS-style duplicate images (e.g., "IMG_1234 2.JPG", "IMG_1234 3.JPG").
Keeps the original file, removes copies.

Two strategies:
  1. name-only: Remove files matching " 2", " 3", etc. pattern (fast)
  2. hash: Compare file hashes to verify true duplicates (slower, safer)

Usage:
  # Dry run (default) - preview what would be deleted
  python3 remove_macos_duplicates.py /path/to/folder

  # Actually delete duplicates
  python3 remove_macos_duplicates.py /path/to/folder --no-dry-run

  # Use hash comparison for safety
  python3 remove_macos_duplicates.py /path/to/folder --verify-hash --no-dry-run

  # Move duplicates to trash folder instead of deleting
  python3 remove_macos_duplicates.py /path/to/folder --trash --no-dry-run
"""

import argparse
import hashlib
import os
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple


# Supported image extensions
IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
    '.tiff', '.tif', '.heic', '.heif', '.dng', '.cr2',
    '.nef', '.arw', '.orf', '.raw'
}

# Pattern: "filename 2.ext", "filename 3.ext", etc.
DUPLICATE_PATTERN = re.compile(r'^(.+)\s+(\d+)(\.[^.]+)$')


def get_file_hash(filepath: Path, quick: bool = True) -> str:
    """
    Calculate file hash.
    
    Args:
        filepath: Path to file
        quick: If True, only hash first 64KB + last 64KB (faster for large files)
    
    Returns:
        MD5 hash string
    """
    hasher = hashlib.md5()
    
    with open(filepath, 'rb') as f:
        if quick:
            # Quick hash: first 64KB + file size + last 64KB
            hasher.update(f.read(65536))
            f.seek(0, 2)  # End of file
            size = f.tell()
            hasher.update(str(size).encode())
            if size > 65536:
                f.seek(-65536, 2)
                hasher.update(f.read(65536))
        else:
            # Full hash
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
    
    return hasher.hexdigest()


def find_duplicates_by_pattern(folder: Path, recursive: bool = False) -> Dict[Path, List[Path]]:
    """
    Find duplicates by macOS naming pattern.
    
    Returns:
        Dict mapping original file -> list of duplicate copies
    """
    # Collect all image files
    if recursive:
        files = [f for f in folder.rglob('*') if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
    else:
        files = [f for f in folder.glob('*') if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
    
    # Group by potential original name
    originals: Dict[str, Path] = {}
    duplicates: Dict[str, List[Path]] = defaultdict(list)
    
    for filepath in files:
        filename = filepath.name
        match = DUPLICATE_PATTERN.match(filename)
        
        if match:
            # This is a copy: "name 2.ext" or "name 3.ext"
            base_name = match.group(1)
            copy_num = int(match.group(2))
            extension = match.group(3)
            original_name = f"{base_name}{extension}"
            
            duplicates[original_name].append((copy_num, filepath))
        else:
            # This might be an original
            originals[filename] = filepath
    
    # Match duplicates to their originals
    result: Dict[Path, List[Path]] = {}
    
    for original_name, dup_list in duplicates.items():
        if original_name in originals:
            # Original exists - these are duplicates
            original_path = originals[original_name]
            # Sort by copy number and extract paths
            sorted_dups = [path for _, path in sorted(dup_list)]
            result[original_path] = sorted_dups
        else:
            # No original found - keep the lowest numbered copy as "original"
            sorted_all = sorted(dup_list)
            # The first one becomes the "original"
            pseudo_original = sorted_all[0][1]
            # Rest are duplicates
            rest = [path for _, path in sorted_all[1:]]
            if rest:
                result[pseudo_original] = rest
    
    return result


def verify_duplicates_by_hash(
    duplicates: Dict[Path, List[Path]],
    quick_hash: bool = True
) -> Dict[Path, List[Path]]:
    """
    Verify duplicates by comparing file hashes.
    
    Returns:
        Dict with only verified duplicates (same hash as original)
    """
    verified: Dict[Path, List[Path]] = {}
    
    for original, copies in duplicates.items():
        if not original.exists():
            continue
            
        original_hash = get_file_hash(original, quick=quick_hash)
        original_size = original.stat().st_size
        
        verified_copies = []
        for copy_path in copies:
            if not copy_path.exists():
                continue
                
            # Quick size check first
            copy_size = copy_path.stat().st_size
            if copy_size != original_size:
                print(f"  ⚠ Size mismatch: {copy_path.name} ({copy_size}) vs original ({original_size})")
                continue
            
            # Hash comparison
            copy_hash = get_file_hash(copy_path, quick=quick_hash)
            if copy_hash == original_hash:
                verified_copies.append(copy_path)
            else:
                print(f"  ⚠ Hash mismatch: {copy_path.name}")
        
        if verified_copies:
            verified[original] = verified_copies
    
    return verified


def remove_duplicates(
    duplicates: Dict[Path, List[Path]],
    dry_run: bool = True,
    use_trash: bool = False,
    trash_dir: Path = None
) -> Tuple[int, int]:
    """
    Remove duplicate files.
    
    Args:
        duplicates: Dict mapping original -> list of duplicates
        dry_run: If True, only print what would be done
        use_trash: If True, move to trash folder instead of deleting
        trash_dir: Trash folder path
    
    Returns:
        Tuple of (files_removed, bytes_freed)
    """
    files_removed = 0
    bytes_freed = 0
    
    for original, copies in duplicates.items():
        print(f"\n📁 Original: {original.name}")
        
        for copy_path in copies:
            if not copy_path.exists():
                continue
                
            size = copy_path.stat().st_size
            size_mb = size / (1024 * 1024)
            
            if dry_run:
                print(f"  [DRY] Would remove: {copy_path.name} ({size_mb:.2f} MB)")
            else:
                try:
                    if use_trash and trash_dir:
                        trash_dir.mkdir(parents=True, exist_ok=True)
                        dest = trash_dir / copy_path.name
                        # Handle name collision in trash
                        counter = 1
                        while dest.exists():
                            dest = trash_dir / f"{copy_path.stem}_{counter}{copy_path.suffix}"
                            counter += 1
                        shutil.move(str(copy_path), str(dest))
                        print(f"  ✓ Moved to trash: {copy_path.name}")
                    else:
                        copy_path.unlink()
                        print(f"  ✓ Deleted: {copy_path.name}")
                    
                    files_removed += 1
                    bytes_freed += size
                except Exception as e:
                    print(f"  ✗ Error removing {copy_path.name}: {e}")
    
    return files_removed, bytes_freed


def main():
    parser = argparse.ArgumentParser(
        description="Remove macOS-style duplicate images",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview duplicates (dry run)
  python3 %(prog)s ~/Documents/aipicsdec2025

  # Actually remove duplicates
  python3 %(prog)s ~/Documents/aipicsdec2025 --no-dry-run

  # Verify with hash before removing
  python3 %(prog)s ~/Documents/aipicsdec2025 --verify-hash --no-dry-run

  # Move to trash instead of delete
  python3 %(prog)s ~/Documents/aipicsdec2025 --trash --no-dry-run

  # Process subdirectories recursively  
  python3 %(prog)s ~/Documents/aipicsdec2025 -r --no-dry-run
        """
    )
    
    parser.add_argument('folder', type=Path, help="Folder to scan for duplicates")
    parser.add_argument('-r', '--recursive', action='store_true',
                       help="Process subdirectories recursively")
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help="Preview changes without deleting (default)")
    parser.add_argument('--no-dry-run', dest='dry_run', action='store_false',
                       help="Actually delete duplicate files")
    parser.add_argument('--verify-hash', action='store_true',
                       help="Verify duplicates by file hash (slower but safer)")
    parser.add_argument('--full-hash', action='store_true',
                       help="Use full file hash instead of quick hash")
    parser.add_argument('--trash', action='store_true',
                       help="Move duplicates to trash folder instead of deleting")
    parser.add_argument('--trash-dir', type=Path, default=None,
                       help="Custom trash directory (default: <folder>/_duplicates_trash)")
    
    args = parser.parse_args()
    
    if not args.folder.exists():
        print(f"Error: Folder not found: {args.folder}", file=sys.stderr)
        sys.exit(1)
    
    if not args.folder.is_dir():
        print(f"Error: Not a directory: {args.folder}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Scanning for duplicates in: {args.folder}")
    print(f"Recursive: {args.recursive}")
    
    # Find duplicates by naming pattern
    duplicates = find_duplicates_by_pattern(args.folder, args.recursive)
    
    if not duplicates:
        print("\n✓ No duplicates found!")
        sys.exit(0)
    
    # Count totals
    total_duplicates = sum(len(copies) for copies in duplicates.values())
    total_size = sum(
        sum(p.stat().st_size for p in copies if p.exists())
        for copies in duplicates.values()
    )
    
    print(f"\nFound {total_duplicates} duplicate files "
          f"({total_size / (1024*1024):.2f} MB) in {len(duplicates)} groups")
    
    # Verify by hash if requested
    if args.verify_hash:
        print("\n🔍 Verifying duplicates by file hash...")
        duplicates = verify_duplicates_by_hash(duplicates, quick_hash=not args.full_hash)
        
        verified_count = sum(len(copies) for copies in duplicates.values())
        print(f"Verified {verified_count} true duplicates")
        
        if verified_count == 0:
            print("\n✓ No verified duplicates to remove!")
            sys.exit(0)
    
    # Setup trash directory
    trash_dir = args.trash_dir
    if args.trash and not trash_dir:
        trash_dir = args.folder / "_duplicates_trash"
    
    # Remove duplicates
    if args.dry_run:
        print("\n📋 DRY RUN - No files will be deleted")
        print("Use --no-dry-run to actually remove files\n")
    
    removed, freed = remove_duplicates(
        duplicates,
        dry_run=args.dry_run,
        use_trash=args.trash,
        trash_dir=trash_dir
    )
    
    # Summary
    print(f"\n{'='*60}")
    print("Summary:")
    print(f"{'='*60}")
    
    if args.dry_run:
        print(f"Would remove: {removed} files ({freed / (1024*1024):.2f} MB)")
        print("\n💡 Run with --no-dry-run to actually delete files")
    else:
        print(f"Removed: {removed} files ({freed / (1024*1024):.2f} MB freed)")
        if args.trash:
            print(f"Trash folder: {trash_dir}")


if __name__ == '__main__':
    main()
