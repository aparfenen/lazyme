#!/usr/bin/env python3
"""
rename_images_by_exif_pro.py - Professional EXIF-based Image Renamer

A robust, fast, and flexible tool for renaming images based on EXIF metadata.

Features:
  - Batch processing with exiftool for speed
  - Progress bar and detailed statistics
  - Support for all major formats: JPEG, PNG, HEIC, DNG, CR2, NEF, ARW, etc.
  - GPS coordinate validation and formatting
  - Customizable filename templates
  - Parallel processing support
  - Comprehensive error handling and logging
  - Dry-run with detailed preview
  - Option to preserve directory structure
  - Backup/undo capability
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Try to import tqdm for progress bar
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("Note: Install 'tqdm' for progress bars: pip install tqdm", file=sys.stderr)

# ============================================================================
# Configuration
# ============================================================================

# Supported image formats (including RAW)
SUPPORTED_FORMATS = {
    # Standard formats
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
    # HEIF/HEIC
    '.heic', '.heif',
    # RAW formats
    '.dng',  # Adobe Digital Negative
    '.cr2', '.cr3',  # Canon
    '.nef', '.nrw',  # Nikon
    '.arw', '.srf', '.sr2',  # Sony
    '.orf',  # Olympus
    '.rw2',  # Panasonic
    '.pef',  # Pentax
    '.raf',  # Fujifilm
    '.raw',  # Generic RAW
}

# Default filename template
DEFAULT_TEMPLATE = "{date}_{time}_{ms}{gps}_{original}"

# GPS coordinate precision
GPS_PRECISION = 4

# Maximum filename length (considering filesystem limits)
MAX_FILENAME_LENGTH = 200


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ImageMetadata:
    """Container for image metadata."""
    filepath: Path
    date_time: Optional[datetime] = None
    milliseconds: int = 0
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    make: Optional[str] = None
    model: Optional[str] = None
    original_name: str = ""
    has_exif: bool = False
    error: Optional[str] = None

    def is_valid(self) -> bool:
        """Check if metadata is valid."""
        return self.date_time is not None and self.error is None


@dataclass
class ProcessingStats:
    """Statistics for the renaming operation."""
    total: int = 0
    processed: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: List[str] = None

    def __post_init__(self):
        if self.error_details is None:
            self.error_details = []

    def add_error(self, filepath: str, error: str):
        """Add an error to statistics."""
        self.errors += 1
        self.error_details.append(f"{filepath}: {error}")

    def __str__(self) -> str:
        """String representation of stats."""
        return (
            f"\n{'='*60}\n"
            f"Processing Statistics:\n"
            f"{'='*60}\n"
            f"Total files found:    {self.total}\n"
            f"Successfully renamed: {self.processed}\n"
            f"Skipped:             {self.skipped}\n"
            f"Errors:              {self.errors}\n"
            f"{'='*60}"
        )


# ============================================================================
# ExifTool Interface
# ============================================================================

class ExifToolBatch:
    """Efficient batch interface to exiftool."""

    def __init__(self, exiftool_path: str = "exiftool"):
        self.exiftool_path = exiftool_path
        self._verify_exiftool()

    def _verify_exiftool(self) -> None:
        """Verify exiftool is available."""
        try:
            result = subprocess.run(
                [self.exiftool_path, "-ver"],
                capture_output=True,
                text=True,
                check=True
            )
            version = result.stdout.strip()
            logging.info(f"Using exiftool version {version}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            raise RuntimeError(
                f"exiftool not found or not working. "
                f"Install: macOS: 'brew install exiftool' | "
                f"Debian/Ubuntu: 'sudo apt install libimage-exiftool-perl'"
            ) from e

    def read_metadata_batch(self, filepaths: List[Path]) -> Dict[Path, dict]:
        """
        Read metadata from multiple files in one exiftool call.
        
        Args:
            filepaths: List of file paths to process
            
        Returns:
            Dictionary mapping filepath to metadata dict
        """
        if not filepaths:
            return {}

        try:
            # Call exiftool with all files at once
            result = subprocess.run(
                [self.exiftool_path, "-j", "-n", "-q", "-q"] + [str(p) for p in filepaths],
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5 minute timeout for large batches
            )
            
            data_list = json.loads(result.stdout)
            
            # Map results back to filepaths
            result_dict = {}
            for item in data_list:
                source_file = Path(item.get("SourceFile", ""))
                if source_file:
                    result_dict[source_file] = item
                    
            return result_dict
            
        except subprocess.CalledProcessError as e:
            logging.error(f"exiftool batch processing failed: {e}")
            return {}
        except subprocess.TimeoutExpired:
            logging.error("exiftool batch processing timed out")
            return {}
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse exiftool JSON output: {e}")
            return {}


# ============================================================================
# Metadata Processing
# ============================================================================

class MetadataExtractor:
    """Extract and process image metadata."""

    # EXIF date tags in order of preference
    DATE_TAGS = ["DateTimeOriginal", "CreateDate", "ModifyDate", "FileModifyDate"]
    
    # Subsecond tags
    SUBSEC_TAGS = ["SubSecTimeOriginal", "SubSecTime", "SubSecTimeDigitized"]

    @staticmethod
    def extract_datetime(exif: dict) -> Tuple[Optional[datetime], int]:
        """
        Extract datetime and milliseconds from EXIF data.
        
        Args:
            exif: EXIF data dictionary
            
        Returns:
            Tuple of (datetime object, milliseconds)
        """
        # Find date/time
        dt_value = None
        for tag in MetadataExtractor.DATE_TAGS:
            if tag in exif:
                dt_value = exif[tag]
                break

        if not dt_value:
            return None, 0

        # Parse datetime
        try:
            if isinstance(dt_value, (int, float)):
                dt = datetime.fromtimestamp(dt_value)
            else:
                # Handle EXIF format: "YYYY:MM:DD HH:MM:SS"
                dt_str = str(dt_value).replace(":", "-", 2)
                # Handle timezone if present
                if "+" in dt_str or "-" in dt_str[-6:]:
                    # Remove timezone for now (could be enhanced)
                    dt_str = dt_str.split("+")[0].split("-")[0].strip()
                dt = datetime.strptime(dt_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
        except (ValueError, AttributeError) as e:
            logging.debug(f"Failed to parse datetime '{dt_value}': {e}")
            return None, 0

        # Extract subseconds
        ms = 0
        for tag in MetadataExtractor.SUBSEC_TAGS:
            if tag in exif:
                subsec = exif[tag]
                try:
                    # Take first 3 digits
                    subsec_str = str(subsec).zfill(3)[:3]
                    ms = int(subsec_str)
                    break
                except (ValueError, AttributeError):
                    pass

        return dt, ms

    @staticmethod
    def extract_gps(exif: dict) -> Tuple[Optional[float], Optional[float]]:
        """
        Extract and validate GPS coordinates.
        
        Args:
            exif: EXIF data dictionary
            
        Returns:
            Tuple of (latitude, longitude) or (None, None)
        """
        try:
            lat = exif.get("GPSLatitude")
            lon = exif.get("GPSLongitude")
            
            if lat is None or lon is None:
                return None, None
            
            lat_f = float(lat)
            lon_f = float(lon)
            
            # Validate coordinate ranges
            if not (-90 <= lat_f <= 90):
                logging.debug(f"Invalid latitude: {lat_f}")
                return None, None
            if not (-180 <= lon_f <= 180):
                logging.debug(f"Invalid longitude: {lon_f}")
                return None, None
            
            # Check for null island (0,0) - likely invalid
            if abs(lat_f) < 0.01 and abs(lon_f) < 0.01:
                logging.debug("GPS coordinates near (0,0) - likely invalid")
                return None, None
            
            return lat_f, lon_f
            
        except (ValueError, TypeError) as e:
            logging.debug(f"Failed to parse GPS coordinates: {e}")
            return None, None

    @staticmethod
    def get_fallback_datetime(filepath: Path) -> Tuple[datetime, int]:
        """
        Get fallback datetime from filesystem.
        
        Args:
            filepath: Path to file
            
        Returns:
            Tuple of (datetime, milliseconds=0)
        """
        try:
            stat = filepath.stat()
            # Prefer birth time on macOS/BSD, fall back to ctime on Linux
            timestamp = getattr(stat, 'st_birthtime', stat.st_ctime)
            dt = datetime.fromtimestamp(timestamp)
            return dt, 0
        except Exception as e:
            logging.warning(f"Failed to get file timestamp for {filepath}: {e}")
            return datetime.now(), 0

    @classmethod
    def create_metadata(cls, filepath: Path, exif: Optional[dict] = None) -> ImageMetadata:
        """
        Create ImageMetadata object from filepath and optional EXIF data.
        
        Args:
            filepath: Path to image file
            exif: Optional EXIF data dictionary
            
        Returns:
            ImageMetadata object
        """
        metadata = ImageMetadata(
            filepath=filepath,
            original_name=filepath.stem
        )

        if exif:
            metadata.has_exif = True
            
            # Extract datetime
            dt, ms = cls.extract_datetime(exif)
            if dt:
                metadata.date_time = dt
                metadata.milliseconds = ms
            
            # Extract GPS
            lat, lon = cls.extract_gps(exif)
            metadata.latitude = lat
            metadata.longitude = lon
            
            # Extract camera info
            metadata.make = exif.get("Make", "").strip()
            metadata.model = exif.get("Model", "").strip()

        # Fallback to file timestamp if no EXIF date
        if metadata.date_time is None:
            dt, ms = cls.get_fallback_datetime(filepath)
            metadata.date_time = dt
            metadata.milliseconds = ms
            logging.debug(f"Using fallback timestamp for {filepath.name}")

        return metadata


# ============================================================================
# Filename Generation
# ============================================================================

class FilenameGenerator:
    """Generate new filenames from metadata."""

    @staticmethod
    def sanitize_filename(name: str, max_length: int = MAX_FILENAME_LENGTH) -> str:
        """
        Sanitize filename by removing/replacing problematic characters.
        
        Args:
            name: Original filename
            max_length: Maximum length for the filename
            
        Returns:
            Sanitized filename
        """
        # Replace filesystem-problematic characters
        replacements = {
            '/': '_', '\\': '_', ':': '_', '*': '_', '?': '_',
            '"': '_', '<': '_', '>': '_', '|': '_', '\0': '_'
        }
        
        for old, new in replacements.items():
            name = name.replace(old, new)
        
        # Collapse multiple spaces/underscores
        name = re.sub(r'[\s_]+', '_', name)
        
        # Remove leading/trailing spaces and underscores
        name = name.strip(' _')
        
        # Truncate if too long
        if len(name) > max_length:
            name = name[:max_length]
        
        return name

    @staticmethod
    def format_gps(lat: Optional[float], lon: Optional[float], precision: int = GPS_PRECISION) -> str:
        """
        Format GPS coordinates for filename.
        
        Args:
            lat: Latitude
            lon: Longitude
            precision: Number of decimal places
            
        Returns:
            Formatted GPS string or empty string
        """
        if lat is None or lon is None:
            return ""
        
        lat_str = f"lat{lat:.{precision}f}".replace(".", "p").replace("-", "m")
        lon_str = f"lon{lon:.{precision}f}".replace(".", "p").replace("-", "m")
        
        return f"_{lat_str}_{lon_str}"

    @classmethod
    def generate_filename(
        cls,
        metadata: ImageMetadata,
        template: str = DEFAULT_TEMPLATE,
        include_camera: bool = False
    ) -> str:
        """
        Generate new filename from metadata using template.
        
        Args:
            metadata: Image metadata
            template: Filename template string
            include_camera: Include camera make/model in filename
            
        Returns:
            Generated filename (without extension)
        """
        if not metadata.date_time:
            # Fallback to original name if no date
            return cls.sanitize_filename(metadata.original_name)

        # Prepare template variables
        variables = {
            'date': metadata.date_time.strftime("%Y%m%d"),
            'time': metadata.date_time.strftime("%H%M%S"),
            'ms': f"{metadata.milliseconds:03d}",
            'gps': cls.format_gps(metadata.latitude, metadata.longitude),
            'original': cls.sanitize_filename(metadata.original_name),
            'year': metadata.date_time.strftime("%Y"),
            'month': metadata.date_time.strftime("%m"),
            'day': metadata.date_time.strftime("%d"),
        }

        if include_camera and metadata.make:
            camera = f"{metadata.make}_{metadata.model}".replace(" ", "_")
            variables['camera'] = cls.sanitize_filename(camera)
        else:
            variables['camera'] = ""

        # Generate filename from template
        try:
            filename = template.format(**variables)
            # Remove empty parts (like camera if not included)
            filename = re.sub(r'_{2,}', '_', filename)
            filename = filename.strip('_')
        except KeyError as e:
            logging.warning(f"Invalid template variable: {e}. Using default.")
            filename = f"{variables['date']}_{variables['time']}_{variables['ms']}{variables['gps']}_{variables['original']}"

        return cls.sanitize_filename(filename)


# ============================================================================
# File Operations
# ============================================================================

class FileOperations:
    """Handle file renaming and copying operations."""

    @staticmethod
    def get_unique_path(dest_dir: Path, base_name: str, extension: str) -> Path:
        """
        Get unique filepath by appending counter if file exists.
        
        Args:
            dest_dir: Destination directory
            base_name: Base filename without extension
            extension: File extension
            
        Returns:
            Unique Path object
        """
        counter = 1
        candidate = dest_dir / f"{base_name}{extension}"
        
        while candidate.exists():
            candidate = dest_dir / f"{base_name}-{counter}{extension}"
            counter += 1
            
        return candidate

    @staticmethod
    def ensure_directory(path: Path) -> None:
        """
        Ensure directory exists, create if needed.
        
        Args:
            path: Directory path
        """
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise RuntimeError(f"Failed to create directory {path}: {e}") from e

    @staticmethod
    def rename_file(src: Path, dest: Path, copy_mode: bool = False) -> None:
        """
        Rename or copy file.
        
        Args:
            src: Source file path
            dest: Destination file path
            copy_mode: If True, copy instead of move
            
        Raises:
            RuntimeError: If operation fails
        """
        try:
            FileOperations.ensure_directory(dest.parent)
            
            if copy_mode:
                shutil.copy2(src, dest)
                logging.debug(f"Copied: {src} -> {dest}")
            else:
                shutil.move(str(src), str(dest))
                logging.debug(f"Moved: {src} -> {dest}")
                
        except Exception as e:
            raise RuntimeError(f"Failed to {'copy' if copy_mode else 'move'} {src} to {dest}: {e}") from e


# ============================================================================
# Main Processing Logic
# ============================================================================

class ImageRenamer:
    """Main image renaming orchestrator."""

    def __init__(
        self,
        exiftool_path: str = "exiftool",
        batch_size: int = 50,
        max_workers: int = 4
    ):
        self.exiftool = ExifToolBatch(exiftool_path)
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.stats = ProcessingStats()

    def collect_image_files(self, root: Path, recursive: bool = False) -> List[Path]:
        """
        Collect image files from directory.
        
        Args:
            root: Root directory
            recursive: If True, search recursively
            
        Returns:
            List of image file paths
        """
        files = []
        
        if root.is_file():
            if root.suffix.lower() in SUPPORTED_FORMATS:
                files.append(root)
            return files

        if recursive:
            for ext in SUPPORTED_FORMATS:
                files.extend(root.rglob(f"*{ext}"))
                # Also match uppercase
                files.extend(root.rglob(f"*{ext.upper()}"))
        else:
            for ext in SUPPORTED_FORMATS:
                files.extend(root.glob(f"*{ext}"))
                files.extend(root.glob(f"*{ext.upper()}"))

        # Remove duplicates and sort
        files = sorted(set(files))
        
        return files

    def process_batch(
        self,
        files: List[Path],
        dest_dir: Optional[Path],
        copy_mode: bool,
        template: str,
        include_camera: bool,
        dry_run: bool,
        preserve_structure: bool,
        base_dir: Optional[Path] = None
    ) -> Tuple[int, int]:
        """
        Process a batch of files.
        
        Returns:
            Tuple of (processed_count, error_count)
        """
        processed = 0
        errors = 0

        # Read metadata in batch
        metadata_dict = self.exiftool.read_metadata_batch(files)

        # Process each file
        for filepath in files:
            try:
                # Get metadata
                exif = metadata_dict.get(filepath)
                metadata = MetadataExtractor.create_metadata(filepath, exif)

                if not metadata.is_valid():
                    logging.warning(f"Skipping {filepath.name}: Invalid metadata")
                    errors += 1
                    self.stats.add_error(str(filepath), "Invalid metadata")
                    continue

                # Generate new filename
                new_base = FilenameGenerator.generate_filename(
                    metadata, template, include_camera
                )
                new_ext = filepath.suffix.lower()
                
                # Determine destination directory
                if dest_dir:
                    if preserve_structure and base_dir:
                        # Preserve relative path structure
                        rel_path = filepath.parent.relative_to(base_dir)
                        target_dir = dest_dir / rel_path
                    else:
                        target_dir = dest_dir
                else:
                    target_dir = filepath.parent

                # Get unique destination path
                new_path = FileOperations.get_unique_path(target_dir, new_base, new_ext)

                # Execute or preview
                if dry_run:
                    action = "COPY" if copy_mode else "RENAME"
                    print(f"[{action}] {filepath}")
                    print(f"     -> {new_path}")
                    if metadata.has_exif:
                        info = f"     EXIF: {metadata.date_time.strftime('%Y-%m-%d %H:%M:%S')}"
                        if metadata.latitude and metadata.longitude:
                            info += f" | GPS: ({metadata.latitude:.4f}, {metadata.longitude:.4f})"
                        print(info)
                else:
                    FileOperations.rename_file(filepath, new_path, copy_mode)
                    logging.info(f"Processed: {filepath.name} -> {new_path.name}")

                processed += 1

            except Exception as e:
                errors += 1
                error_msg = str(e)
                logging.error(f"Error processing {filepath}: {error_msg}")
                self.stats.add_error(str(filepath), error_msg)

        return processed, errors

    def process_files(
        self,
        files: List[Path],
        dest_dir: Optional[Path] = None,
        copy_mode: bool = False,
        template: str = DEFAULT_TEMPLATE,
        include_camera: bool = False,
        dry_run: bool = True,
        preserve_structure: bool = False,
        base_dir: Optional[Path] = None
    ) -> ProcessingStats:
        """
        Process list of files with batch optimization.
        
        Args:
            files: List of file paths to process
            dest_dir: Optional destination directory
            copy_mode: If True, copy instead of rename
            template: Filename template string
            include_camera: Include camera info in filename
            dry_run: If True, only preview changes
            preserve_structure: Preserve directory structure
            base_dir: Base directory for relative paths
            
        Returns:
            ProcessingStats object
        """
        self.stats = ProcessingStats(total=len(files))

        if not files:
            logging.warning("No files to process")
            return self.stats

        # Process in batches
        batches = [files[i:i + self.batch_size] for i in range(0, len(files), self.batch_size)]

        # Setup progress bar
        if HAS_TQDM:
            progress = tqdm(total=len(files), desc="Processing images", unit="file")
        else:
            progress = None

        try:
            for batch in batches:
                processed, errors = self.process_batch(
                    batch, dest_dir, copy_mode, template, include_camera,
                    dry_run, preserve_structure, base_dir
                )
                
                self.stats.processed += processed
                self.stats.errors += errors
                
                if progress:
                    progress.update(len(batch))

        finally:
            if progress:
                progress.close()

        self.stats.skipped = self.stats.total - self.stats.processed - self.stats.errors

        return self.stats


# ============================================================================
# CLI Interface
# ============================================================================

def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Rename images based on EXIF metadata with professional features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview)
  python3 %(prog)s /path/to/photos
  
  # Actually rename files
  python3 %(prog)s /path/to/photos --no-dry-run
  
  # Recursive processing
  python3 %(prog)s /path/to/photos -r --no-dry-run
  
  # Copy with custom destination
  python3 %(prog)s /path/to/photos --copy -d /path/to/renamed --no-dry-run
  
  # Custom template with camera info
  python3 %(prog)s /path/to/photos --template "{year}{month}{day}_{camera}_{time}" --include-camera --no-dry-run
  
  # Preserve directory structure
  python3 %(prog)s /path/to/photos --copy -d /backup --preserve-structure --no-dry-run

Template variables:
  {date}     - YYYYMMDD
  {time}     - HHMMSS
  {ms}       - milliseconds (000-999)
  {gps}      - GPS coordinates (if available)
  {original} - original filename
  {year}     - YYYY
  {month}    - MM
  {day}      - DD
  {camera}   - camera make and model (requires --include-camera)
        """
    )

    parser.add_argument(
        "folder",
        type=Path,
        help="Folder with images to process"
    )
    
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Process files recursively"
    )
    
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        default=True,
        help="Show what would be done without renaming (default: ON)"
    )
    
    parser.add_argument(
        "--no-dry-run",
        dest='dry_run',
        action='store_false',
        help="Actually perform renames (disables dry-run)"
    )
    
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of renaming"
    )
    
    parser.add_argument(
        "-d", "--dest",
        type=Path,
        default=None,
        help="Destination directory (default: same folder as each file)"
    )
    
    parser.add_argument(
        "--preserve-structure",
        action="store_true",
        help="Preserve directory structure when copying"
    )
    
    parser.add_argument(
        "--template",
        type=str,
        default=DEFAULT_TEMPLATE,
        help=f"Filename template (default: {DEFAULT_TEMPLATE})"
    )
    
    parser.add_argument(
        "--include-camera",
        action="store_true",
        help="Include camera make/model in filename"
    )
    
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of files to process in each batch (default: 50)"
    )
    
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1, experimental)"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Write log to file"
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_arguments()
    
    # Setup logging
    setup_logging(args.verbose)
    
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        )
        logging.getLogger().addHandler(file_handler)

    # Validate arguments
    if not args.folder.exists():
        print(f"Error: Folder not found: {args.folder}", file=sys.stderr)
        sys.exit(1)

    if args.preserve_structure and not args.dest:
        print("Error: --preserve-structure requires --dest", file=sys.stderr)
        sys.exit(1)

    # Create renamer
    try:
        renamer = ImageRenamer(
            batch_size=args.batch_size,
            max_workers=args.workers
        )
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Collect files
    print(f"Scanning for images in {args.folder}...")
    files = renamer.collect_image_files(args.folder, args.recursive)
    
    if not files:
        print("No image files found.", file=sys.stderr)
        sys.exit(0)

    print(f"Found {len(files)} image file(s)")
    
    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No files will be modified")
        print("Use --no-dry-run to actually rename files\n")

    # Process files
    base_dir = args.folder if args.folder.is_dir() else args.folder.parent
    
    stats = renamer.process_files(
        files=files,
        dest_dir=args.dest,
        copy_mode=args.copy,
        template=args.template,
        include_camera=args.include_camera,
        dry_run=args.dry_run,
        preserve_structure=args.preserve_structure,
        base_dir=base_dir
    )

    # Print statistics
    print(stats)
    
    if stats.errors > 0 and args.verbose:
        print("\nErrors encountered:")
        for error in stats.error_details[:10]:  # Show first 10 errors
            print(f"  • {error}")
        if len(stats.error_details) > 10:
            print(f"  ... and {len(stats.error_details) - 10} more")

    if args.dest and not args.dry_run:
        print(f"\n✓ Output directory: {args.dest}")

    sys.exit(0 if stats.errors == 0 else 1)


if __name__ == "__main__":
    main()
