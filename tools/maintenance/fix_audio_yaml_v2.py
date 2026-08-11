"""
批量修复 audio_manifest.yaml 中的文件名格式
支持嵌套目录: 301/1/1.mp3 → 301/001/001.mp3
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_manifest = ROOT / "config" / "audio_manifest.yaml"

# 读取文件
with open(_manifest, 'r', encoding='utf-8') as f:
    content = f.read()

# 备份原始内容用于统计
original = content

# 模式1: 两层目录 (301/1/1.mp3 → 301/001/001.mp3)
pattern_nested = r'path: "(\d+)/(\d+)/(\d+)\.mp3"(.*)'
def replace_nested(match):
    dir1 = match.group(1)
    dir2 = match.group(2)
    filename = match.group(3)
    comment = match.group(4)
    return f'path: "{dir1}/{dir2.zfill(3)}/{filename.zfill(3)}.mp3"{comment}'

content = re.sub(pattern_nested, replace_nested, content)

# 模式2: 单层目录 (016/1.mp3 → 016/001.mp3) - 已经在第一次运行时处理过
pattern_single = r'path: "(\d+)/(\d+)\.mp3"(.*)'
def replace_single(match):
    directory = match.group(1)
    filename = match.group(2)
    comment = match.group(3)
    return f'path: "{directory}/{filename.zfill(3)}.mp3"{comment}'

content = re.sub(pattern_single, replace_single, content)

# 写回文件
with open(_manifest, 'w', encoding='utf-8') as f:
    f.write(content)

# 统计
nested_count = len(re.findall(pattern_nested, original))
single_count = len(re.findall(pattern_single, original))

print("✅ 文件名格式修复完成！")
print(f"   - 两层目录修复: {nested_count} 个")
print(f"   - 单层目录修复: {single_count} 个")
print(f"   - 总计: {nested_count + single_count} 个")
