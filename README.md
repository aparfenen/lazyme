# LazyMe - Personal Automation Toolbox
A set of scripts for everyday life. Each tool is standalone, minimal, and easy to understand — designed to simplify common file, image, or data management tasks.


## Module: image_tools
### Script: rename_images_by_exif.py
**Purpose:** Rename image files using EXIF metadata — creation date, precise tim (milliseconds), and GPS coordinates (if available).  
**Supported formats:** HEIC, HEIF, JPG, PNG, TIFF, GIF, WEBP, BMP.  
**Filename format:** `YYYYMMDD_HHMMSS_mmm[_latXX.XXXX_lonYY.YYYY]_{originalbasename}.{ext}`
- mmm — milliseconds (if available, else 000)
- GPS coordinates added only when both latitude and longitude exist
- Extension converted to lowercase
- Conflicting names get suffixed with -1, -2, etc.


## Usage
### Create a virtual environment (recommended)
```bash
cd ~/projects/lazyme
python3 -m venv .venv
source .venv/bin/activate
```
### Setup
**Install exiftool:**  
`brew install exiftool` (macOS);  
`sudo apt install libimage-exiftool-perl` (Ubuntu/Debian)  

### dry run (shows planned renames)
```python3 image_tools/rename_images_by_exif.py <path_to_imgs_dir>```

### rename in place
```python3 image_tools/rename_images_by_exif.py <path_to_imgs_dir> --no-dry-run```

### copy renamed files to a new folder
```
mkdir -p ~/Documents/<path_to_imgs_dir_renamed>
python3 image_tools/rename_images_by_exif.py <path_to_imgs_dir> --copy -d <path_to_imgs_dir_renamed> --no-dry-run
```

### process subfolders recursively
```python3 image_tools/rename_images_by_exif.py <path_to_imgs_dir> -r --no-dry-run```

