"""Generate Camera Viewer.icns for macOS."""
import math
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SIZES = [16, 32, 64, 128, 256, 512, 1024]


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    p = size / 1024  # scale factor

    # Background rounded rect — dark blue-grey
    r = size * 0.18
    bg_color = (18, 22, 36, 255)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=bg_color)

    # Camera body
    cx, cy = size / 2, size / 2
    bw, bh = size * 0.60, size * 0.40
    bx, by = cx - bw / 2, cy - bh / 2 + size * 0.04
    br = size * 0.06
    body_color = (52, 58, 80, 255)
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=br, fill=body_color)

    # Viewfinder bump on top-left
    vw, vh = bw * 0.28, bh * 0.28
    vx, vy = bx + bw * 0.12, by - vh * 0.7
    vr = size * 0.03
    d.rounded_rectangle([vx, vy, vx + vw, vy + vh], radius=vr, fill=body_color)

    # Lens outer ring
    lo_r = bh * 0.36
    d.ellipse([cx - lo_r, cy + size*0.04 - lo_r, cx + lo_r, cy + size*0.04 + lo_r],
              fill=(30, 34, 52, 255), outline=(80, 90, 130, 255),
              width=max(1, int(size * 0.012)))

    # Lens middle ring
    lm_r = lo_r * 0.72
    d.ellipse([cx - lm_r, cy + size*0.04 - lm_r, cx + lm_r, cy + size*0.04 + lm_r],
              fill=(20, 24, 42, 255))

    # Lens inner glow
    li_r = lo_r * 0.44
    d.ellipse([cx - li_r, cy + size*0.04 - li_r, cx + li_r, cy + size*0.04 + li_r],
              fill=(0, 102, 204, 255))

    # Lens highlight
    hl_r = li_r * 0.42
    hl_x = cx - hl_r * 0.6
    hl_y = cy + size * 0.04 - hl_r * 1.3
    d.ellipse([hl_x, hl_y, hl_x + hl_r * 1.2, hl_y + hl_r * 0.9],
              fill=(180, 220, 255, 120))

    # Flash dot
    fd_r = size * 0.03
    fd_x = bx + bw * 0.82
    fd_y = by + bh * 0.28
    d.ellipse([fd_x - fd_r, fd_y - fd_r, fd_x + fd_r, fd_y + fd_r],
              fill=(255, 200, 60, 255))

    # "EP" initials badge — bottom right
    badge_r = size * 0.175
    badge_cx = size * 0.78
    badge_cy = size * 0.78
    # Badge circle with blue accent
    d.ellipse(
        [badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r],
        fill=(0, 102, 204, 255),
    )
    # Text
    font_size = int(badge_r * 1.05)
    font = None
    for font_path, idx in [
        ("/System/Library/Fonts/Helvetica.ttc", 0),
        ("/Library/Fonts/Arial Bold.ttf", 0),
        ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
        ("/System/Library/Fonts/SFNSRounded.ttf", 0),
        ("/System/Library/Fonts/SFNSDisplay.ttf", 0),
    ]:
        try:
            font = ImageFont.truetype(font_path, font_size, index=idx)
            # quick smoke-test — catches division-by-zero on bad faces
            d.textbbox((0, 0), "EP", font=font)
            break
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()

    text = "EP"
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = badge_cx - tw / 2 - bbox[0]
    ty = badge_cy - th / 2 - bbox[1]
    d.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

    return img


def build_icns(out_path: Path):
    iconset = Path("/tmp/CameraViewer.iconset")
    iconset.mkdir(exist_ok=True)

    for s in SIZES:
        img = draw_icon(s)
        img.save(iconset / f"icon_{s}x{s}.png")
        if s <= 512:
            img2 = draw_icon(s * 2)
            img2.save(iconset / f"icon_{s}x{s}@2x.png")

    import subprocess
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out_path)], check=True)
    shutil.rmtree(iconset)
    print(f"Created: {out_path}")


if __name__ == "__main__":
    out = Path("icon.icns")
    build_icns(out)
