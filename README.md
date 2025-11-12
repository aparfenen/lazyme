# LazyMe - Personal Automation Toolbox
A set of scripts for everyday life.  
Each tool is standalone, minimal, and easy to understand — designed to simplify common file, image, or data management tasks.


## Module: image_tools
Image manipulations toolbox.

### Script: rename_images_by_exif.py
**Purpose**  
Rename image files using EXIF metadata — creation date, precise time (milliseconds), and GPS coordinates (if available).  
If EXIF data is missing, uses file creation time as a fallback.  
---
**How it works**
1. Reads metadata via `exiftool`.
2. Extracts `DateTimeOriginal`, `SubSecTime*`, and `GPSLatitude`/`GPSLongitude`.
3. Falls back to filesystem **creation time** if no EXIF date is found.
4. Builds a clean, unique, timestamp-based filename and safely renames (or copies) files.  
---
**Supported formats:** HEIC, HEIF, JPG, JPEG, PNG, TIFF, GIF, WEBP, BMP.  
---
**Notes:**  
- Requires `exiftool` installed and available in PATH.  
- On macOS uses true file creation time (`st_birthtime`); on Linux falls back to inode change time (`st_ctime`).  
- Reverse geocoding (city/country) not implemented.  
- Tested on macOS 26.1 (Tahoe), Python 3.14, exiftool 12.98.  
- Handles Unicode and special characters in filenames safely.  
---
**Filename format:**  
`YYYYMMDD_HHMMSS_mmm[_latXX.XXXX_lonYY.YYYY]_{originalbasename}.{ext}`  
- `mmm` — milliseconds (if available, else `000`)  
- GPS coordinates added only when both latitude and longitude exist  
- Extensions normalized to lowercase  
- Duplicate target names automatically suffixed with `-1`, `-2`, etc.  


#### Usage
**Create a virtual environment (recommended)**:  
```bash
cd ~/projects/lazyme
python3 -m venv .venv
source .venv/bin/activate
```

**Install exiftool:**  
`brew install exiftool` (macOS);  
`sudo apt install libimage-exiftool-perl` (Ubuntu/Debian)  

**Option 1: Dry run (preview only: shows planned renames):**
```
python3 image_tools/rename_images_by_exif.py <path_to_imgs_dir>
```

**Option 2: Rename in place (disable dry-run):**
```
python3 image_tools/rename_images_by_exif.py <path_to_imgs_dir> --no-dry-run
```

**Option 3: Copy renamed files to a new folder:**
```
mkdir -p ~/Documents/<path_to_imgs_dir_renamed>
python3 image_tools/rename_images_by_exif.py <path_to_imgs_dir> --copy -d <path_to_imgs_dir_renamed> --no-dry-run
```

**Option 4: Process subfolders recursively:**
```
python3 image_tools/rename_images_by_exif.py <path_to_imgs_dir> -r --no-dry-run
```



