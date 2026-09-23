from pathlib import Path
from PIL import Image, ImageFilter
src=Path("facebook_assets/news_copyright_fine_cover.jpg")
dst=Path("facebook_assets/news_copyright_fine_cover_approved.jpg")
with Image.open(src) as im:
    im=im.convert("RGB")
    # Preserve the exact approved composition; only resample/encode.
    im=im.resize((1080,1440), Image.Resampling.LANCZOS)
    im=im.filter(ImageFilter.UnsharpMask(radius=1.0, percent=70, threshold=3))
    im.save(dst,"JPEG",quality=94,subsampling=0,optimize=False,progressive=False)
print("APPROVED_ASSET_READY",dst)
