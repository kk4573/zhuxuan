"""竹喧 · 生成应用图标（app.ico）

想换图标就改下面的颜色和字，重跑这个脚本：
    .venv/Scripts/python.exe tests/make_icon.py

输出：
    app.ico（项目根目录）        —— 给 PyInstaller 用（多尺寸，系统按场合自己挑）
    图标预览.png（项目根目录）    —— 256×256 预览，方便肉眼确认
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ICO = ROOT / "app.ico"
PREVIEW = ROOT / "图标预览.png"

SIZE = 256
BG = (24, 27, 35, 255)          # 背景：和界面卡片同色（#181b23）
EDGE = (46, 52, 68, 255)        # 描边：和界面边框同色
FG = (95, 211, 168, 255)        # 竹青
GLYPH = "竹"
FONT_PATH = "C:/Windows/Fonts/msyhbd.ttc"
FONT_SIZE = 150


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角底板
    d.rounded_rectangle([1, 1, SIZE - 2, SIZE - 2], radius=58, fill=BG, outline=EDGE, width=3)

    # 字：手工算居中（比 anchor 稳，中文字体的基线偏移不好靠 anchor 处理）
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    box = font.getbbox(GLYPH)                       # (x0, y0, x1, y1)
    gw, gh = box[2] - box[0], box[3] - box[1]
    x = (SIZE - gw) / 2 - box[0]
    y = (SIZE - gh) / 2 - box[1] - 4                # 略微上提，视觉更居中
    d.text((x, y), GLYPH, font=font, fill=FG)

    img.save(ICO, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    img.save(PREVIEW)

    # 自检：字形有没有偏、留白够不够
    glyph_box = font.getbbox(GLYPH)
    left = x + glyph_box[0]
    right = x + glyph_box[2]
    top = y + glyph_box[1]
    bottom = y + glyph_box[3]
    print(f"字形 {gw}×{gh} 像素（画布 {SIZE}）")
    print(f"留白  左{left:.0f} 右{SIZE-right:.0f} 上{top:.0f} 下{SIZE-bottom:.0f}")
    ok_lr = abs((left) - (SIZE - right)) <= 2
    ok_tb = abs((top) - (SIZE - bottom)) <= 8
    print(f"左右居中：{'✓' if ok_lr else '✗'}    上下基本居中：{'✓' if ok_tb else '✗'}")
    print(f"已生成 {ICO.name}（含 6 种尺寸）和 {PREVIEW.name}")

    # 顺手看看 16×16 缩下来还认不认得出（笔画多的字容易糊）
    tiny = img.resize((16, 16), Image.LANCZOS)
    colors = {c for _, c in tiny.convert("RGB").getcolors(256) or []}
    print(f"16×16 缩略图里有 {len(colors)} 种颜色（越多说明细节越糊）")


if __name__ == "__main__":
    main()
