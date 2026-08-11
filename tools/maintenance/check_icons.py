"""检查数据库中的icon字段"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask
from database.models import db, Course, CourseItem
from app.config import Config

# 创建临时app实例
temp_app = Flask(__name__)
temp_app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
temp_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(temp_app)

with temp_app.app_context():
    print("=== Course Icons ===")
    courses = Course.query.limit(5).all()
    for c in courses:
        print(f"Course {c.id}: title={c.title}, icon={c.icon}")
    
    print("\n=== CourseItem Icons ===")
    items = CourseItem.query.limit(10).all()
    for i in items:
        print(f"Item {i.id}: name={i.name}, icon={i.icon}, media_file={i.media_file}")
    
    print("\n=== Course JSON Output ===")
    if courses:
        import json
        print(json.dumps(courses[0].to_dict(), ensure_ascii=False, indent=2))
