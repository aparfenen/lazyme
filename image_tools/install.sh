#!/bin/bash
# Installation Script for Image Orientation Tools

echo "Setting up image orientation tools..."

# Create image_tools directory if it doesn't exist
mkdir -p ~/projects/lazyme/image_tools

# Copy the scripts to the correct location
echo "Installing scripts..."
cp check_orientations.py ~/projects/lazyme/image_tools/
cp heic_orient.py ~/projects/lazyme/image_tools/
cp orient_pro.py ~/projects/lazyme/image_tools/
cp orient_simple.py ~/projects/lazyme/image_tools/

# Make them executable
chmod +x ~/projects/lazyme/image_tools/*.py

echo "✓ Scripts installed to ~/projects/lazyme/image_tools/"
echo ""
echo "Usage examples:"
echo ""
echo "1. Simple orientation fix (recommended):"
echo "   cd ~/projects/lazyme"
echo "   python3 image_tools/orient_simple.py ~/Documents/imgs"
echo ""
echo "2. Check what needs fixing:"
echo "   python3 image_tools/check_orientations.py ~/Documents/imgs"
echo ""
echo "3. Fix with the pro version:"
echo "   python3 image_tools/orient_pro.py ~/Documents/imgs --mode exif --no-dry-run"
echo ""
echo "4. Process HEIC files only:"
echo "   python3 image_tools/heic_orient.py ~/Documents/imgs --no-dry-run"
