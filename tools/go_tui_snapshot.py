#!/usr/bin/env python3
import os
import sys
import subprocess
import argparse
from PIL import Image, ImageDraw, ImageFont

# ANSI color codes mapping (simplified)
ANSI_COLORS = {
    '0': (0, 0, 0),       # Black
    '1': (187, 0, 0),     # Red
    '2': (0, 187, 0),     # Green
    '3': (187, 187, 0),   # Yellow
    '4': (0, 0, 187),     # Blue
    '5': (187, 0, 187),   # Magenta
    '6': (0, 187, 187),   # Cyan
    '7': (187, 187, 187), # White
    '90': (85, 85, 85),   # Bright Black (Gray)
    '91': (255, 85, 85),  # Bright Red
    '92': (85, 255, 85),  # Bright Green
    '93': (255, 255, 85), # Bright Yellow
    '94': (85, 85, 255),  # Bright Blue
    '95': (255, 85, 255), # Bright Magenta
    '96': (85, 255, 255), # Bright Cyan
    '97': (255, 255, 255),# Bright White
}

def clean_ansi(text):
    """Simple ANSI cleaner for now, returns plain text."""
    # This is a very basic stripper. For full color support we'd need a real ANSI parser.
    # For this task, let's just strip codes to make the text readable in the image.
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def render_text_to_image(text, output_path):
    lines = text.split('\n')
    
    # Font settings
    font_size = 14
    try:
        # Try to use a monospaced font available on typical Linux systems
        font = ImageFont.truetype("NotoSansMono-Regular.ttf", font_size)
    except IOError:
        try:
             font = ImageFont.truetype("DejaVuSansMono.ttf", font_size)
        except IOError:
            print("Warning: Monospace font not found, using default.")
            font = ImageFont.load_default()

    # Calculate image size
    # Measure a typical character
    char_w = font.getlength("A")
    # Approximate line height
    char_h = int(font_size * 1.5)
    
    max_line_len = 0
    for line in lines:
        w = font.getlength(clean_ansi(line))
        if w > max_line_len:
            max_line_len = w
            
    width = int(max_line_len + 40) # Padding
    height = int(len(lines) * char_h + 40)

    # Create image
    # Dark background like a terminal
    bg_color = (30, 30, 30) 
    fg_color = (200, 200, 200)
    
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    y = 20
    for line in lines:
        clean_line = clean_ansi(line)
        d.text((20, y), clean_line, font=font, fill=fg_color)
        y += char_h
        
    img.save(output_path)
    print(f"Snapshot saved to: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Generate Go TUI snapshot")
    parser.add_argument("--mode", default="raw", choices=["raw", "event", "timeline"], help="View mode")
    parser.add_argument("--logview", default="all", choices=["all", "out", "err"], help="Log view")
    parser.add_argument("--scenario", default="success", choices=["success", "failure"], help="Snapshot scenario")
    parser.add_argument("--out", help="Output PNG path")
    args = parser.parse_args()

    # 1. Build binary if needed
    bin_path = "/tmp/chipflow-tui-go"
    if not os.path.exists(bin_path):
        print("Building binary...")
        cmd = ["go", "build", "-o", bin_path, "./cmd/chipflow-tui-go"]
        subprocess.check_call(cmd)

    # 2. Run binary to get text snapshot
    txt_out = "/tmp/snapshot_out.txt"
    cmd = [
        bin_path,
        "--snapshot-out", txt_out,
        "--snapshot-width", "120",
        "--snapshot-height", "40",
        "--snapshot-view", args.mode,
        "--snapshot-logview", args.logview,
        "--snapshot-scenario", args.scenario,
    ]
    
    print(f"Running: {' '.join(cmd)}")
    subprocess.check_call(cmd)

    # 3. Read text
    with open(txt_out, "r") as f:
        content = f.read()

    # 4. Render to PNG
    if args.out:
        out_path = args.out
    else:
        suffix = args.mode if args.scenario == "success" else f"{args.mode}_{args.scenario}"
        out_path = f"artifacts/screenshots/go_tui_snapshot_{suffix}.png"
        
    # Ensure dir exists
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    
    render_text_to_image(content, out_path)

if __name__ == "__main__":
    main()
