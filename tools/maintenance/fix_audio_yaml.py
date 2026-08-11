"""
批量修复 audio_manifest.yaml 中的文件名格式
从 1.mp3 改为 001.mp3
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_manifest = ROOT / "config" / "audio_manifest.yaml"

# 读取文件
with open(_manifest, 'r', encoding='utf-8') as f:
    content = f.read()

# 正则替换：匹配 "path: "数字目录/数字.mp3"" 格式
# 例如：path: "016/1.mp3" -> path: "016/001.mp3"
def replace_func(match):
    dir_num = match.group(1)
    file_num = match.group(2)
    comment = match.group(3)  # 可能的注释
    
    # 将文件编号填充为3位数
    file_num_padded = file_num.zfill(3)
    
    if comment:
        return f'path: "{dir_num}/{file_num_padded}.mp3"{comment}'
    else:
        return f'path: "{dir_num}/{file_num_padded}.mp3"'

# 匹配模式：- path: "数字/数字.mp3" [可选注释]
pattern = r'path: "(\d+)/(\d+)\.mp3"(.*)'
fixed_content = re.sub(pattern, replace_func, content)

# 写回文件
with open(_manifest, 'w', encoding='utf-8') as f:
    f.write(fixed_content)

print("✅ 文件名格式修复完成！")
print(f"总共修复了 {len(re.findall(pattern, content))} 个文件路径")
