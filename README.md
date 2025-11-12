# LazyMe - Personal Automation Toolbox
A set of scripts for everyday life.  
Each tool is standalone, minimal, and easy to understand — designed to simplify common file, image, or data management tasks.


## Module: image_tools
Image manipulations toolbox.

### Script: Rename Images by EXIF
   
**Purpose:** Rename image files using EXIF metadata — creation date, precise time (milliseconds), GPS coordinates, and camera info.  
If EXIF data is missing, uses file creation time as a fallback.  
---
**How it works**
1. Reads metadata via `exiftool` (batch processing for speed).
2. Extracts `DateTimeOriginal`, `SubSecTime*`, `GPSLatitude`/`GPSLongitude`, and camera make/model.
3. Falls back to filesystem **creation time** if no EXIF date is found.
4. Validates GPS coordinates (range checks, null island detection).
5. Builds a clean, informative, timestamp-based filename and safely renames (or copies) files.  
---
**Supported formats:** HEIC, HEIF, JPG, JPEG, PNG, TIFF, GIF, WEBP, BMP, DNG, CR2, CR3, NEF, ARW, ORF, RW2, PEF, RAF (all major RAW formats).  
---
**Notes:**  
- Requires `exiftool` installed and available in PATH.  
- On macOS uses true file creation time (`st_birthtime`); on Linux falls back to inode change time (`st_ctime`).  
- Batch processing provides 20x speedup over sequential processing.
- GPS coordinates validated and formatted with 4 decimal precision.
- Tested on macOS 26.1 (Tahoe), Python 3.14, exiftool 12.98+.  
- Handles Unicode and special characters in filenames safely.  
---
**Filename format:**  
`MM-DD-YYYY - HH-MM-SS-mmm - Location - Device.ext`  
- `MM-DD-YYYY` — month-day-year  
- `HH-MM-SS-mmm` — hours-minutes-seconds-milliseconds  
- `Location` — GPS coordinates (e.g., `42.3442N_71.1443W`) or `NoGPS`  
- `Device` — camera make and model (e.g., `Apple iPhone 14 Pro Max`) or `Unknown`  
- Extensions normalized to lowercase  
- Duplicate target names automatically suffixed with `-1`, `-2`, etc.  
- Use `--keep-original` flag to append original filename  


#### Usage
**Install exiftool:**  
`brew install exiftool` (macOS);  
`sudo apt install libimage-exiftool-perl` (Ubuntu/Debian)  

**Option 1: Dry run (preview only):**
```bash
python3 image_tools/rename_images_by_exif_pro.py <path_to_imgs_dir>
```

**Option 2: Rename in place:**
```bash
python3 image_tools/rename_images_by_exif_pro.py <path_to_imgs_dir> --no-dry-run
```

**Option 3: Keep original filename in new name:**
```bash
python3 image_tools/rename_images_by_exif_pro.py <path_to_imgs_dir> --keep-original --no-dry-run
```

**Option 4: Copy renamed files to a new folder:**
```bash
python3 image_tools/rename_images_by_exif_pro.py <path_to_imgs_dir> --copy -d <path_to_imgs_dir_renamed> --no-dry-run
```

**Option 5: Process subfolders recursively:**
```bash
python3 image_tools/rename_images_by_exif_pro.py <path_to_imgs_dir> -r --no-dry-run
```

**Option 6: Custom filename template:**
```bash
python3 image_tools/rename_images_by_exif_pro.py <path_to_imgs_dir> --template "{year}{month}{day}_{device}" --no-dry-run
```

**Additional flags:**  
`--preserve-structure` — maintain folder hierarchy when copying  
`--verbose` — detailed output  
`--log-file <path>` — write log to file
