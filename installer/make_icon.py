"""Draws the SCraMic Share icon (same design as web/assets/logo.svg) as a Windows .ico."""
import sys
from PIL import Image, ImageDraw


def draw(size):
    s = size * 4                      # draw big, scale down = smooth edges
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):                # diagonal-ish orange gradient
        t = y / s
        gd.line([(0, y), (s, y)], fill=(255, int(154 - 64 * t), int(61 - 30 * t), 255))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((s * 0.03, s * 0.03, s * 0.97, s * 0.97), s * 0.25, fill=255)
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    w = max(2, int(s * 0.0625))
    d.rounded_rectangle((s * 0.27, s * 0.19, s * 0.58, s * 0.75), s * 0.08, outline="white", width=w)
    r = s * 0.037
    d.ellipse((s * 0.42 - r, s * 0.64 - r, s * 0.42 + r, s * 0.64 + r), fill="white")
    for k, rad in ((0, 0.16), (1, 0.27)):
        box = (s * (0.67 - rad), s * (0.47 - rad), s * (0.67 + rad), s * (0.47 + rad))
        d.arc(box, -55, 55, fill="white", width=w)
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "scramicshare.ico"
    big = draw(256)
    big.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
