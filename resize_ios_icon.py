from PIL import Image
import os

input_path = "c:/Users/ADMIN/Desktop/mirai.ai/assets/m@4x 1.png"
output_path = "c:/Users/ADMIN/Desktop/mirai.ai/assets/ios_icon_1024.png"

try:
    img = Image.open(input_path)
    # Resize with high-quality resampling
    img = img.resize((1024, 1024), Image.Resampling.LANCZOS)
    img.save(output_path, "PNG")
    print(f"SUCCESS: Created {output_path}")
except Exception as e:
    print(f"ERROR: {e}")
