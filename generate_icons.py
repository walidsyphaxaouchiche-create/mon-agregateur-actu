from PIL import Image, ImageDraw
import os

def create_icon(size, output_path):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Fond dégradé bleu-violet
    for y in range(size):
        r = int(37 + (124 - 37) * y / size)
        g = int(99 + (58 - 99) * y / size)
        b = int(235 + (237 - 235) * y / size)
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))
    
    # Coins arrondis
    mask = Image.new('L', (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, size, size], radius=size//5, fill=255)
    img.putalpha(mask)
    
    # Chouette stylisée
    cx, cy = size // 2, size // 2
    s = size // 10
    
    # Corps
    body_points = [
        (cx - 3*s, cy - 2*s),
        (cx + 3*s, cy - 2*s),
        (cx + 4*s, cy + 2*s),
        (cx, cy + 4*s),
        (cx - 4*s, cy + 2*s),
    ]
    draw.polygon(body_points, fill=(255, 255, 255, 255))
    
    # Yeux
    eye_y = cy - s
    eye_r = int(s * 0.8)
    draw.ellipse([cx - 2*s - eye_r, eye_y - eye_r, cx - 2*s + eye_r, eye_y + eye_r], fill=(37, 99, 235, 255))
    draw.ellipse([cx + 2*s - eye_r, eye_y - eye_r, cx + 2*s + eye_r, eye_y + eye_r], fill=(37, 99, 235, 255))
    
    # Pupilles
    pupil_r = int(s * 0.35)
    draw.ellipse([cx - 2*s - pupil_r, eye_y - pupil_r, cx - 2*s + pupil_r, eye_y + pupil_r], fill=(255, 255, 255, 255))
    draw.ellipse([cx + 2*s - pupil_r, eye_y - pupil_r, cx + 2*s + pupil_r, eye_y + pupil_r], fill=(255, 255, 255, 255))
    
    # Bec
    beak_points = [
        (cx - s//2, cy + s),
        (cx + s//2, cy + s),
        (cx, cy + 2*s),
    ]
    draw.polygon(beak_points, fill=(245, 158, 11, 255))
    
    img.save(output_path, 'PNG')
    print(f'Created {output_path}')

static_dir = os.path.join(os.path.dirname(__file__), 'static')
os.makedirs(static_dir, exist_ok=True)
create_icon(192, os.path.join(static_dir, 'icon-192.png'))
create_icon(512, os.path.join(static_dir, 'icon-512.png'))
