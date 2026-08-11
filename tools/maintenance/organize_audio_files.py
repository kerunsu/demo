"""
音频文件重组脚本
将 static/resources/audios/ 中单独的音频文件移动到相应的子文件夹中
例如: 015.mp3 -> 015/001.mp3
"""

import os
import shutil
from pathlib import Path

# 仓库根目录（本文件位于 tools/maintenance/）
ROOT = Path(__file__).resolve().parent.parent.parent


def organize_audio_files():
    """重新组织音频文件结构"""
    audios_dir = ROOT / "static" / "resources" / "audios"
    
    if not audios_dir.exists():
        print(f"错误: 目录不存在 {audios_dir}")
        return
    
    print(f"开始处理目录: {audios_dir}")
    print("-" * 60)
    
    # 获取所有项目
    items = list(audios_dir.iterdir())
    
    # 分类: 文件 vs 文件夹
    audio_files = []
    existing_folders = []
    
    for item in items:
        if item.is_file() and item.suffix.lower() in ['.mp3', '.wav', '.m4a']:
            audio_files.append(item)
        elif item.is_dir():
            existing_folders.append(item.name)
    
    print(f"找到 {len(audio_files)} 个单独的音频文件")
    print(f"找到 {len(existing_folders)} 个已存在的子文件夹")
    print("-" * 60)
    
    # 处理每个音频文件
    moved_count = 0
    skipped_count = 0
    
    for audio_file in audio_files:
        # 获取文件名（不含扩展名）作为文件夹名
        folder_name = audio_file.stem  # 例如: 015.mp3 -> 015
        target_folder = audios_dir / folder_name
        
        # 检查文件夹是否已存在
        if target_folder.exists():
            print(f"⚠️  跳过: {audio_file.name} (文件夹 {folder_name}/ 已存在)")
            skipped_count += 1
            continue
        
        # 创建目标文件夹
        target_folder.mkdir(exist_ok=True)
        
        # 移动文件并重命名为 001.mp3
        target_file = target_folder / f"001{audio_file.suffix}"
        
        try:
            shutil.move(str(audio_file), str(target_file))
            print(f"✓ 移动: {audio_file.name} -> {folder_name}/001{audio_file.suffix}")
            moved_count += 1
        except Exception as e:
            print(f"✗ 错误: 移动 {audio_file.name} 失败 - {e}")
    
    print("-" * 60)
    print(f"完成! 成功移动 {moved_count} 个文件, 跳过 {skipped_count} 个文件")
    
    # 验证结果
    print("\n验证结果:")
    remaining_files = [f for f in audios_dir.iterdir() 
                      if f.is_file() and f.suffix.lower() in ['.mp3', '.wav', '.m4a']]
    
    if remaining_files:
        print(f"⚠️  仍有 {len(remaining_files)} 个音频文件未处理:")
        for f in remaining_files:
            print(f"   - {f.name}")
    else:
        print("✓ 所有音频文件都已移入子文件夹!")


if __name__ == "__main__":
    # 确认操作
    print("=" * 60)
    print("音频文件重组脚本")
    print("=" * 60)
    print("此脚本将:")
    print("1. 扫描 static/resources/audios/ 中的所有音频文件")
    print("2. 为每个文件创建同名子文件夹")
    print("3. 将文件移动到子文件夹中并重命名为 001.mp3")
    print()
    print("例如: 015.mp3 -> 015/001.mp3")
    print("=" * 60)
    
    response = input("确认执行? (y/n): ").strip().lower()
    
    if response == 'y':
        organize_audio_files()
    else:
        print("操作已取消")
