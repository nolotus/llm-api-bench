"""Render cover + data cards for social posts (3:4, 1080x1440)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path('results/cards')
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1080, 1440
BG = (16, 18, 24)
FG = (240, 244, 250)
DIM = (150, 160, 175)
ACC = (124, 196, 255)
WARN = (255, 176, 96)
GOOD = (128, 220, 160)

FONT_PATHS = [
    '/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
]


def font(size: int, bold: bool = False):
    for p in FONT_PATHS:
        if Path(p).exists():
            try:
                f = ImageFont.truetype(p, size)
                try:
                    f.set_variation_by_name('Bold' if bold else 'Regular')
                except Exception:
                    pass
                return f
            except Exception:
                continue
    return ImageFont.load_default()


def new_card():
    img = Image.new('RGB', (W, H), BG)
    return img, ImageDraw.Draw(img)


def header(d, title, sub=None, tag=None):
    d.rectangle([0, 0, W, 8], fill=ACC)
    d.text((64, 70), title, font=font(58, True), fill=FG)
    if sub:
        d.text((64, 152), sub, font=font(30), fill=DIM)
    if tag:
        d.text((64, 206), tag, font=font(26), fill=WARN)


def table(d, x, y, widths, headers, rows, row_h=64, fs=28, hfs=26):
    cx = x
    for w, h in zip(widths, headers):
        d.text((cx, y), h, font=font(hfs, True), fill=DIM)
        cx += w
    y += row_h - 12
    d.line([(x, y), (x + sum(widths), y)], fill=(60, 66, 78), width=2)
    y += 14
    for i, row in enumerate(rows):
        cx = x
        for w, cell in zip(widths, row):
            text, color = cell if isinstance(cell, tuple) else (cell, FG)
            d.text((cx, y), str(text), font=font(fs), fill=color)
            cx += w
        y += row_h
        if i < len(rows) - 1:
            d.line([(x, y - 16), (x + sum(widths), y - 16)], fill=(40, 44, 54), width=1)
    return y


def footer(d, lines):
    y = H - 40 - 34 * len(lines)
    for ln in lines:
        d.text((64, y), ln, font=font(26), fill=DIM)
        y += 34


# ---------- card 1: cover ----------
img, d = new_card()
d.rectangle([0, 0, W, 8], fill=ACC)
d.text((64, 120), '同一个模型', font=font(72, True), fill=FG)
d.text((64, 210), '五家供应商 · 九个档位', font=font(72, True), fill=ACC)
d.text((64, 330), 'DeepSeek V4.1 Flash 实测', font=font(34), fill=DIM)

stats = [
    ('5', '供应商'),
    ('9', '档位'),
    ('32K', '上下文'),
    ('n=30', '持续压测'),
]
x = 64
for num, label in stats:
    d.text((x, 460), num, font=font(84, True), fill=FG)
    d.text((x, 566), label, font=font(28), fill=DIM)
    x += 250

d.line([(64, 650), (W - 64, 650)], fill=(50, 55, 66), width=2)
d.text((64, 700), '4K 输入，持续压测 30 次/档', font=font(30), fill=DIM)
rows = [
    ('Lithos Base', '1138', '2129', '3%', '0%'),
    ('Lithos Ultra', '1434', '3113', '13%', '0%'),
    ('Lithos Fast', '1906', '3941', ('23%', WARN), '0%'),
]
table(d, 64, 780, [300, 150, 150, 150, 170],
      ['档位', 'P50', 'P95', '慢>3s', '无正文'],
      [(a, b, c, d_, e) for a, b, c, d_, e in rows])
footer(d, ['时间 2026-10-20 单日 · 单位 ms · 费用为估算非账单', '数据为实测记录，不构成排名或选购建议'])
img.save(OUT / 'cover.png')

# ---------- card 2: cache ----------
img, d = new_card()
header(d, '缓存命中率', '同一前缀，冷请求完成后再发暖请求', '含会话亲和键 x-session-affinity')
rows = [
    ('Fireworks', ('0 → 8/8', GOOD), '0%', '95.9%'),
    ('Baseten Standard', ('0 → 5/8', GOOD), '0%', '94.6%'),
    ('DeepSeek 官方', '4K', '0%', '92.6%'),
    ('DeepInfra', '4K', '0%', '98.1%'),
    ('Lithos Base', '4K', '0%', '98.6%'),
]
table(d, 64, 320, [330, 190, 180, 180],
      ['供应商/档位', '亲和前后', '冷请求', '暖请求命中'],
      rows)
d.text((64, 900), '多轮追加式对话（1K→16K）', font=font(32, True), fill=FG)
rows2 = [('1轮', '909', '0'), ('2轮', '1786', '50%'), ('3轮', '3539', '47%'),
         ('4轮', '7045', '49%'), ('5轮', '14056', '50%')]
table(d, 64, 970, [220, 260, 260],
      ['轮次', '输入 tokens', '命中率'], rows2, row_h=62, fs=28)
d.text((64, 1290), '命中量 ≈ 上一轮全文；上下文翻倍时上限即 50%', font=font(26), fill=DIM)
footer(d, ['未带亲和键时 Fireworks / Baseten 恒为 0，属我方方法错误', '2026-10-20 实测 · 费用为估算非账单'])
img.save(OUT / 'cache.png')

# ---------- card 3: sustained ----------
img, d = new_card()
header(d, '持续压测明细', '4K 输入 · 5 次/分钟 · 每档 30 次 · 带亲和键')
rows = [
    ('Lithos Base', '1138', '1721', '2129', '2912', '3%', '0%'),
    ('Lithos Ultra', '1434', '2658', '3113', '5265', '13%', '0%'),
    ('Lithos Fast', '1906', '3347', '3941', '4212', ('23%', WARN), '0%'),
]
table(d, 48, 330, [280, 110, 110, 110, 120, 130, 130],
      ['档位', 'P50', 'P90', 'P95', 'P99', '慢>3s', '无正文'], rows, row_h=76, fs=27)
d.text((64, 800), '分桶漂移', font=font(32, True), fill=FG)
d.text((64, 856), '本次每档仅 6 分钟，未形成多桶，未评估漂移', font=font(27), fill=DIM)
d.text((64, 940), '同时段 32K 首 token（批次矩阵）', font=font(32, True), fill=FG)
rows2 = [('DeepSeek 官方', '814', '99.2%'), ('DeepInfra Priority', '878', '99.8%'),
         ('Baseten Standard', '984', '0%'),
         ('Lithos Base', '1915', '99.2%'), ('Lithos Ultra', '2976', '99.8%'),
         ('Lithos Fast', '3165', '99.2%'), ('Fireworks', ('4526', WARN), '0%')]
table(d, 64, 1010, [380, 220, 200], ['档位', 'P50 (ms)', '缓存命中'], rows2, row_h=46, fs=25)
footer(d, ['2026-10-20 单日单地区 · P99 接近 max，样本不足以谈长期稳定性', '费用为估算非账单 · 不构成排名'])
img.save(OUT / 'sustained.png')

# ---------- card 4: method ----------
img, d = new_card()
header(d, '方法与我踩的坑', '不写清楚条件，数字就没有意义', '两处已修正的错误')
items = [
    ('错误 1', '把 UTF-8 字节数当 token 规划输入', '实际输入只有目标的 30–40%'),
    ('错误 2', '测缓存没带 x-session-affinity', '请求落到不同副本，命中恒为 0'),
    ('修正后', 'Fireworks 0 → 8/8（95.9%）', 'Baseten Standard 0 → 5/8'),
]
y = 330
for tag, line1, line2 in items:
    d.text((64, y), tag, font=font(28, True), fill=WARN if tag.startswith(('错误', '未解释')) else GOOD)
    d.text((64, y + 44), line1, font=font(34, True), fill=FG)
    d.text((64, y + 92), line2, font=font(27), fill=DIM)
    y += 190
d.line([(64, 1090), (W - 64, 1090)], fill=(50, 55, 66), width=2)
d.text((64, 1130), '口径', font=font(30, True), fill=FG)
for i, ln in enumerate([
    '费用 = 配置单价 × 上报 usage 的估算，非平台账单',
    '延迟为客户端接收时间，非服务端 token 时间',
    '并发数为客户端在途请求，不等于服务端容量',
    '样本 n=30，P99 接近 max，不代表长期稳定性',
]):
    d.text((64, 1180 + i * 40), '· ' + ln, font=font(26), fill=DIM)
img.save(OUT / 'method.png')

print('\n'.join(str(p) for p in sorted(OUT.glob('*.png'))))