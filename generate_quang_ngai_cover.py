from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math

OUT = Path("facebook_assets/news_copyright_fine_cover_v5.jpg")
W, H = 1080, 1350

def font(size, bold=True):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(p, size)

img = Image.new("RGB",(W,H),(7,10,18))
d = ImageDraw.Draw(img)

# layered dark newsroom gradient
for y in range(H):
    t=y/H
    d.line((0,y,W,y), fill=(int(7+10*t), int(10+8*t), int(18+14*t)))
# red/blue light blooms
for cx,cy,col in [(130,260,(115,15,25)),(930,280,(15,42,105)),(820,880,(125,18,12))]:
    glow=Image.new("RGBA",(W,H),(0,0,0,0)); gd=ImageDraw.Draw(glow)
    for r in range(320,20,-20):
        a=max(0,int(28*(1-r/340)))
        gd.ellipse((cx-r,cy-r,cx+r,cy+r),fill=(*col,a))
    img=Image.alpha_composite(img.convert("RGBA"),glow).convert("RGB")
    d=ImageDraw.Draw(img)

# header
d.rounded_rectangle((55,45,1025,135),radius=22,fill=(194,20,31))
d.text((82,69),"HÓNG CÙNG TÔI  •  TIN ĐÁNG CHÚ Ý",font=font(38),fill="white")

# headline
d.text((60,175),"LẤY TIN BÁO LÀM",font=font(76),fill="white",stroke_width=4,stroke_fill=(0,0,0))
d.text((60,270),"VIDEO",font=font(108),fill=(248,205,22),stroke_width=5,stroke_fill=(0,0,0))
d.rounded_rectangle((400,285,1018,390),radius=20,fill=(180,18,26))
d.text((435,304),"BỊ PHẠT 12,5 TRIỆU",font=font(51),fill="white")

# phone mockup
d.rounded_rectangle((65,470,430,1110),radius=55,fill=(12,15,23),outline=(205,215,230),width=5)
d.rounded_rectangle((92,530,403,890),radius=24,fill=(30,49,68))
# abstract media scene
d.rectangle((112,550,383,685),fill=(45,83,105))
d.rectangle((112,700,383,740),fill=(190,25,30))
d.text((137,706),"TIN TỨC",font=font(28),fill="white")
d.polygon([(220,775),(220,855),(290,815)],fill="white")
d.text((118,920),"VIDEO ĐĂNG MẠNG",font=font(29),fill="white")
for y,wid in [(975,230),(1015,260),(1055,190)]:
    d.rounded_rectangle((118,y,118+wid,y+15),radius=7,fill=(95,105,120))

# newspaper / copyright card
d.rounded_rectangle((500,470,1015,900),radius=30,fill=(235,230,216),outline="white",width=4)
d.text((545,515),"BÁO CHÍ",font=font(56),fill=(28,28,28))
d.line((545,585,955,585),fill=(45,45,45),width=5)
for y,wid in [(630,365),(675,390),(720,340)]:
    d.rounded_rectangle((545,y,545+wid,y+18),radius=8,fill=(105,105,105))
# copyright warning
d.ellipse((655,775,855,975),fill=(205,20,30),outline="white",width=10)
d.text((690,790),"©",font=font(130),fill="white")
d.line((670,955,850,790),fill=(255,215,20),width=24)

# gavel-like legal cue
d.rounded_rectangle((555,1030,895,1080),radius=20,fill=(128,76,26))
d.rounded_rectangle((790,940,930,1040),radius=25,fill=(95,50,18))
d.rectangle((900,980,1000,1015),fill=(150,85,27))

# bottom summary
d.rounded_rectangle((55,1160,1025,1285),radius=28,fill=(15,18,27),outline=(205,25,35),width=4)
d.text((85,1190),"BẢN QUYỀN BÁO CHÍ • DÙNG NỘI DUNG PHẢI ĐÚNG QUY ĐỊNH",font=font(31),fill=(245,245,245))
d.text((85,1242),"Nguồn: Tuổi Trẻ / Công an tỉnh Quảng Ngãi",font=font(24,False),fill=(190,195,205))

OUT.parent.mkdir(parents=True,exist_ok=True)
img.save(OUT,"JPEG",quality=94,subsampling=0,optimize=False,progressive=False)
with Image.open(OUT) as chk:
    chk.load()
    assert chk.size==(1080,1350)
    assert chk.mode=="RGB"
print("V5_COVER_OK",OUT,OUT.stat().st_size)
