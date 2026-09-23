from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path("facebook_assets/news_copyright_fine_cover_v3.jpg")
W, H = 1080, 1350
img = Image.new("RGB", (W, H), (9, 18, 34))
d = ImageDraw.Draw(img)

font_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
font_reg = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def F(size, bold=True):
    return ImageFont.truetype(font_bold if bold else font_reg, size)

# Background panels
for y in range(H):
    r = int(9 + 18 * y / H)
    g = int(18 + 8 * y / H)
    b = int(34 + 18 * y / H)
    d.line((0, y, W, y), fill=(r, g, b))

# Header strip
d.rounded_rectangle((55, 55, W-55, 160), radius=24, fill=(190, 22, 34))
d.text((90, 82), "HÓNG CÙNG TÔI  •  TIN ĐÁNG CHÚ Ý", font=F(42), fill="white")

# Headline block
headline = ["LẤY NỘI DUNG BÁO CHÍ", "LÀM VIDEO CỦA MÌNH"]
y = 220
for line in headline:
    d.text((65, y), line, font=F(68), fill="white", stroke_width=3, stroke_fill=(0,0,0))
    y += 88

d.rounded_rectangle((62, 405, W-62, 560), radius=30, fill=(248, 197, 20))
d.text((95, 430), "BỊ PHẠT 12,5 TRIỆU", font=F(76), fill=(155, 10, 20), stroke_width=2, stroke_fill="white")

# Newspaper card
d.rounded_rectangle((70, 635, 505, 1135), radius=30, fill=(236, 232, 220), outline=(255,255,255), width=4)
d.text((105, 680), "TIN TỨC", font=F(60), fill=(25,25,25))
d.line((105, 755, 465, 755), fill=(55,55,55), width=5)
for yy, ww in [(800,320),(850,350),(900,290),(950,340),(1000,250)]:
    d.rounded_rectangle((110, yy, 110+ww, yy+22), radius=8, fill=(95,95,95))
d.rounded_rectangle((115, 1045, 455, 1100), radius=10, fill=(190,22,34))
d.text((145, 1054), "NỘI DUNG BÁO CHÍ", font=F(28), fill="white")

# Phone / video panel
d.rounded_rectangle((570, 640, 995, 1100), radius=48, fill=(20,24,31), outline=(175,185,205), width=5)
d.rounded_rectangle((610, 700, 955, 970), radius=18, fill=(28,55,82))
d.polygon([(735,775),(735,895),(835,835)], fill=(255,255,255))
d.text((655, 1005), "VIDEO ĐĂNG MẠNG", font=F(34), fill="white")

# Warning / copyright badge
cx, cy, R = 540, 1160, 105
d.ellipse((cx-R,cy-R,cx+R,cy+R), fill=(210,25,35), outline=(255,255,255), width=10)
d.text((cx-58, cy-75), "©", font=F(120), fill="white")
d.line((cx-80,cy+75,cx+80,cy-75), fill=(255,220,30), width=22)

d.text((70, 1270), "Nguồn thông tin: Tuổi Trẻ / Công an tỉnh Quảng Ngãi", font=F(28, False), fill=(220,225,235))

OUT.parent.mkdir(parents=True, exist_ok=True)
img.save(OUT, "JPEG", quality=92, optimize=False, progressive=False)
print("GENERATED", OUT, img.size)
