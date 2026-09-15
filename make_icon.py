"""Generates a cyberpunk-style .ico app icon: a neon lightning glyph on a glowing dark square,
designed to stay legible down to 16x16 (title bar / taskbar size)."""
from PIL import Image, ImageDraw, ImageFilter

SIZE = 256
BG_TOP = (6, 4, 20)
BG_BOTTOM = (16, 4, 30)
CYAN = (40, 255, 235)
MAGENTA = (255, 20, 190)


def gradient_bg():
    img = Image.new("RGB", (SIZE, SIZE), BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(SIZE):
        t = y / SIZE
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        d.line([(0, y), (SIZE, y)], fill=(r, g, b))
    return img.convert("RGBA")


def build():
    img = gradient_bg()
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)

    bolt = [
        (150, 20), (70, 140), (118, 140), (95, 236),
        (196, 108), (146, 108), (176, 20),
    ]

    gd.polygon(bolt, fill=(*CYAN, 255))
    glow_blur = glow.filter(ImageFilter.GaussianBlur(14))
    img = Image.alpha_composite(img, glow_blur)

    d = ImageDraw.Draw(img)
    d.polygon(bolt, fill=(*CYAN, 255))
    d.line(bolt + [bolt[0]], fill=(*MAGENTA, 255), width=3, joint="curve")

    d.rounded_rectangle([6, 6, SIZE - 6, SIZE - 6], radius=40, outline=(*MAGENTA, 230), width=6)

    return img


if __name__ == "__main__":
    icon = build()
    icon.save("app_icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save("app_icon.png")
    print("wrote app_icon.ico / app_icon.png")
