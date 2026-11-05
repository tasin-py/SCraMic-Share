"""Draws the ScramicShare Stream window icon as a Windows .ico: a plain apple on the app's orange."""
import sys
from PIL import Image, ImageDraw


def draw(size):
    s = size * 4                      # draw big, scale down = smooth edges
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):                # same orange as the app logo
        t = y / s
        gd.line([(0, y), (s, y)], fill=(255, int(154 - 64 * t), int(61 - 30 * t), 255))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((s * 0.03, s * 0.03, s * 0.97, s * 0.97), s * 0.25, fill=255)
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    # the fruit: two round shoulders, a dip at the top, and a nearly round base
    d.ellipse((s * 0.16, s * 0.29, s * 0.60, s * 0.80), fill="white")
    d.ellipse((s * 0.40, s * 0.29, s * 0.84, s * 0.80), fill="white")
    d.ellipse((s * 0.24, s * 0.44, s * 0.76, s * 0.87), fill="white")
    # the stem and the leaf
    d.line((s * 0.50, s * 0.36, s * 0.50, s * 0.21), fill="white", width=max(2, int(s * 0.035)))
    leaf = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(leaf).ellipse((s * 0.52, s * 0.15, s * 0.76, s * 0.26), fill="white")
    im.alpha_composite(leaf.rotate(22, center=(s * 0.52, s * 0.22), resample=Image.BICUBIC))
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "stream.ico"
    draw(256).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    if len(sys.argv) > 2:             # optional preview picture
        draw(256).save(sys.argv[2])
    print(out)
