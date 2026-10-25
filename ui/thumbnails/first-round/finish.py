import pathlib
from PIL import Image
HERE = pathlib.Path(__file__).parent
names = sorted(p.stem for p in HERE.glob("thumb-*.png"))
for n in names:
    fd = HERE / "frames" / n
    frames = sorted(fd.glob("*.png")); ms = float((fd / "ms.txt").read_text())
    ims = [Image.open(f).convert("RGB") for f in frames]
    # one shared palette from a strip of frames keeps colours steady across the loop
    strip = Image.new("RGB", (640, 360 * min(6, len(ims))))
    for i, im in enumerate(ims[:: max(1, len(ims) // 6)][:6]): strip.paste(im, (0, 360 * i))
    pal = strip.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    q = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in ims]
    out = HERE / f"{n}.gif"
    q[0].save(out, save_all=True, append_images=q[1:], duration=round(ms), loop=0, optimize=True, disposal=1)
    print(out.name, len(ims), "frames", round(ms), "ms", out.stat().st_size // 1024, "KB")
# contact sheet: 2 columns x 4 rows of 640x360 with labels
W, H, G = 640, 360, 16
sheet = Image.new("RGB", (2 * W + 3 * G, 4 * H + 5 * G), (4, 6, 12))
for i, n in enumerate(names):
    im = Image.open(HERE / f"{n}.png").convert("RGB").resize((W, H), Image.LANCZOS)
    sheet.paste(im, (G + (i % 2) * (W + G), G + (i // 2) * (H + G)))
sheet.save(HERE / "contact-sheet.png")
print("contact-sheet.png", sheet.size)
