"""Generate VurucuTim app icon (multi-resolution PNG + ICO).

Run: python electron/scripts/make-icon.py
Outputs:
  electron/assets/icon.png   (512x512, for tray + general use)
  electron/assets/icon.ico   (multi-res: 16, 32, 48, 64, 128, 256)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


def render(size: int) -> Image.Image:
    """Render logo at the given size."""
    # Work at 4x supersample for clean edges, downscale at the end.
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    # ─── Background: rounded square with subtle gradient ───────────────
    # Single-color base (gradient via paste of vertical strip would be expensive at 4x).
    bg_top = (15, 23, 42)        # slate-900
    bg_bot = (30, 41, 59)        # slate-800
    radius = int(s * 0.22)

    # Manual gradient — top to bottom
    grad = Image.new("RGBA", (s, s), bg_top)
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / s
        r = int(bg_top[0] * (1 - t) + bg_bot[0] * t)
        g = int(bg_top[1] * (1 - t) + bg_bot[1] * t)
        b = int(bg_top[2] * (1 - t) + bg_bot[2] * t)
        gd.line([(0, y), (s, y)], fill=(r, g, b, 255))

    # Rounded mask
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, s, s), radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)

    # ─── Vertical "Shorts" frame (9:16-ish proportion) ─────────────────
    # Centered red frame representing a phone screen / Shorts video.
    frame_w = int(s * 0.42)
    frame_h = int(s * 0.62)
    frame_x = (s - frame_w) // 2
    frame_y = (s - frame_h) // 2
    frame_radius = int(s * 0.06)

    # Outer red glow / border
    border_thick = int(s * 0.025)

    # Filled red rounded rect (the phone-screen)
    yt_red = (255, 0, 51, 255)         # YouTube red, slightly punchy
    yt_red_dark = (200, 0, 30, 255)

    # Drop shadow under the frame
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (frame_x, frame_y + int(s * 0.01),
         frame_x + frame_w, frame_y + frame_h + int(s * 0.01)),
        radius=frame_radius,
        fill=(0, 0, 0, 120),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=int(s * 0.015)))
    img = Image.alpha_composite(img, shadow)

    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle(
        (frame_x, frame_y, frame_x + frame_w, frame_y + frame_h),
        radius=frame_radius,
        fill=yt_red,
    )
    # Inner darker rim for depth
    d.rounded_rectangle(
        (frame_x + border_thick, frame_y + border_thick,
         frame_x + frame_w - border_thick, frame_y + frame_h - border_thick),
        radius=max(frame_radius - border_thick, 4),
        outline=yt_red_dark, width=max(border_thick // 2, 2),
    )

    # ─── Play triangle (white, centered in the frame) ──────────────────
    # Equilateral-ish triangle pointing right.
    tri_w = int(frame_w * 0.40)
    tri_h = int(tri_w * 1.05)
    tri_cx = frame_x + frame_w // 2
    tri_cy = frame_y + frame_h // 2
    pts = [
        (tri_cx - tri_w // 2 + int(s * 0.012), tri_cy - tri_h // 2),
        (tri_cx - tri_w // 2 + int(s * 0.012), tri_cy + tri_h // 2),
        (tri_cx + tri_w // 2 + int(s * 0.012), tri_cy),
    ]
    d.polygon(pts, fill=(255, 255, 255, 255))

    # ─── Bot accent: small spark / star top-right and bottom-left ──────
    spark_color = (96, 165, 250, 230)   # blue-400
    spark_size = int(s * 0.06)
    # Top-right spark (4-pointed star)
    sx, sy = int(s * 0.78), int(s * 0.22)
    d.polygon([
        (sx, sy - spark_size),
        (sx + int(spark_size * 0.4), sy - int(spark_size * 0.4)),
        (sx + spark_size, sy),
        (sx + int(spark_size * 0.4), sy + int(spark_size * 0.4)),
        (sx, sy + spark_size),
        (sx - int(spark_size * 0.4), sy + int(spark_size * 0.4)),
        (sx - spark_size, sy),
        (sx - int(spark_size * 0.4), sy - int(spark_size * 0.4)),
    ], fill=spark_color)
    # Bottom-left spark (smaller)
    sx2, sy2 = int(s * 0.22), int(s * 0.78)
    sp2 = int(s * 0.04)
    d.polygon([
        (sx2, sy2 - sp2),
        (sx2 + int(sp2 * 0.4), sy2 - int(sp2 * 0.4)),
        (sx2 + sp2, sy2),
        (sx2 + int(sp2 * 0.4), sy2 + int(sp2 * 0.4)),
        (sx2, sy2 + sp2),
        (sx2 - int(sp2 * 0.4), sy2 + int(sp2 * 0.4)),
        (sx2 - sp2, sy2),
        (sx2 - int(sp2 * 0.4), sy2 - int(sp2 * 0.4)),
    ], fill=(96, 165, 250, 200))

    # Downscale with high-quality filter
    return img.resize((size, size), Image.LANCZOS)


def main():
    out_dir = Path(__file__).resolve().parent.parent / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    # PNG (high-res, used by tray + general)
    png = render(512)
    png.save(out_dir / "icon.png", "PNG")
    print(f"Wrote {out_dir / 'icon.png'} (512x512)")

    # ICO (multi-resolution for Windows app + installer)
    sizes = [256, 128, 64, 48, 32, 16]
    frames = [render(sz) for sz in sizes]
    frames[0].save(
        out_dir / "icon.ico",
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=frames[1:],
    )
    print(f"Wrote {out_dir / 'icon.ico'} (sizes: {sizes})")


if __name__ == "__main__":
    main()
