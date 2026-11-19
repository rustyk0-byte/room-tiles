from PIL import Image, ImageDraw, ImageFont
S = 8                      # draw at 8x, shrink to 60 px
N = 60 * S
GREEN, DARK, SHADE = (98, 163, 99, 255), (78, 138, 80, 255), (58, 104, 60, 255)
LIGHT, MID, GAP = (216, 218, 220, 255), (158, 161, 165, 255), (58, 63, 69, 255)

def canvas():
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)

def u(v):  # 60-px units -> drawing px
    return v * S

def arrow_up(d, cx, top, bottom, w):
    d.polygon([(u(cx), u(top)), (u(cx + w), u(top + w)), (u(cx - w), u(top + w))], fill=LIGHT)
    d.rectangle([u(cx - w * 0.38), u(top + w - 0.5), u(cx + w * 0.38), u(bottom)], fill=LIGHT)

def arrow_right(d, left, right, cy, w):
    d.polygon([(u(right), u(cy)), (u(right - w), u(cy - w)), (u(right - w), u(cy + w))], fill=LIGHT)
    d.rectangle([u(left), u(cy - w * 0.38), u(right - w + 0.5), u(cy + w * 0.38)], fill=LIGHT)

# A - garage door rising: frame, door raised part way (slats), dark opening below, up arrow
def opt_a():
    im, d = canvas()
    d.rounded_rectangle([u(6), u(8), u(54), u(54)], radius=u(3), fill=MID)          # frame / wall
    d.rectangle([u(10), u(12), u(50), u(54)], fill=GAP)                               # opening
    d.rectangle([u(10), u(12), u(50), u(36)], fill=GREEN)                             # door, half up
    for y in (18, 24, 30):
        d.rectangle([u(10), u(y), u(50), u(y + 0.9)], fill=DARK)                      # slats
    d.rectangle([u(10), u(34.5), u(50), u(36)], fill=SHADE)
    arrow_up(d, 30, 38, 52, 6)
    return im

# B - door swung open, arrow walking in
def opt_b():
    im, d = canvas()
    d.rectangle([u(16), u(6), u(48), u(56)], fill=MID)                                 # frame
    d.rectangle([u(20), u(10), u(44), u(56)], fill=GAP)                                # doorway
    d.polygon([(u(20), u(10)), (u(32), u(14)), (u(32), u(56)), (u(20), u(56))], fill=GREEN)   # open door
    d.polygon([(u(30), u(14.5)), (u(32), u(14)), (u(32), u(56)), (u(30), u(56))], fill=SHADE)
    d.ellipse([u(27.5), u(33), u(30), u(35.5)], fill=LIGHT)                            # handle
    arrow_right(d, 4, 42, 34, 6)
    return im

# C - gate opening: two leaves swung apart between posts, arrow through
def opt_c():
    im, d = canvas()
    d.rectangle([u(4), u(14), u(10), u(56)], fill=MID)
    d.rectangle([u(50), u(14), u(56), u(56)], fill=MID)
    d.polygon([(u(10), u(20)), (u(22), u(26)), (u(22), u(52)), (u(10), u(54))], fill=GREEN)   # left leaf, open
    d.polygon([(u(50), u(20)), (u(38), u(26)), (u(38), u(52)), (u(50), u(54))], fill=GREEN)   # right leaf
    for x0, x1 in ((10, 22), (38, 50)):
        d.line([(u(x0), u(37)), (u(x1), u(39))], fill=DARK, width=round(u(1.2)))
    arrow_up(d, 30, 16, 54, 6)
    return im

# D - closed door with a light key-shaped "go" arrow: door + entry arrow on its face
def opt_d():
    im, d = canvas()
    d.rounded_rectangle([u(12), u(4), u(48), u(58)], radius=u(3), fill=MID)
    d.rectangle([u(16), u(8), u(44), u(58)], fill=GREEN)
    d.rectangle([u(16), u(52), u(44), u(58)], fill=DARK)
    d.ellipse([u(37), u(30), u(40.5), u(33.5)], fill=LIGHT)
    arrow_right(d, 18, 36, 31.5, 5)
    return im

opts = {"A": opt_a(), "B": opt_b(), "C": opt_c(), "D": opt_d()}
small = {k: v.resize((60, 60), Image.LANCZOS) for k, v in opts.items()}
for k, v in small.items():
    v.save(f"/tmp/claude-0/-homeassistant/d55aeab9-da70-4e8f-9c9d-4932c1d96e8e/scratchpad/entry_{k}.png")
blind = Image.open("/share/room-tiles/custom_components/room_tiles/themes/masters/ui/icon_blind.png").convert("RGBA")
Z = 4
cols = list(small.items()) + [("blind (now)", blind)]
sheet = Image.new("RGBA", (len(cols) * (60 * Z + 30) + 30, 60 * Z + 80), (30, 30, 30, 255))
dr = ImageDraw.Draw(sheet)
for i, (k, im) in enumerate(cols):
    x = 30 + i * (60 * Z + 30)
    sheet.alpha_composite(im.resize((60 * Z, 60 * Z), Image.NEAREST), (x, 20))
    dr.text((x + 60 * Z // 2 - 20, 60 * Z + 35), k, fill=(220, 220, 220, 255))
# actual size row
for i, (k, im) in enumerate(cols):
    sheet.alpha_composite(im, (30 + i * (60 * Z + 30), 60 * Z + 20 - 60))
sheet.save("/tmp/claude-0/-homeassistant/d55aeab9-da70-4e8f-9c9d-4932c1d96e8e/scratchpad/entry_options.png")
print("ok")
