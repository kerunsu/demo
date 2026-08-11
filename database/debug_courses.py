"""调试脚本：检查数据库中的课程项"""
import sys
from pathlib import Path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from database.models import db, Course, CourseItem
from app.config import Config
from flask import Flask

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
db.init_app(app)

with app.app_context():
    naming = Course.query.filter_by(title='命名课程').first()
    if naming:
        print(f'命名课程 ID: {naming.id}')
        print(f'课程项总数: {len(naming.items)}')
        print(f'\n前5个课程项:')
        for item in naming.items[:5]:
            print(f'  ID={item.id}, name={item.name}')
            print(f'    media_file={item.media_file}')
            print(f'    type={item.type}')
    else:
        print('命名课程不存在')
    
    print('\n\n检查 /courses API 返回的数据:')
    courses = Course.query.all()
    for course in courses[:3]:
        data = course.to_dict()
        print(f"课程 {data['id']}: {data['title']}")
        for item in data.get('items', [])[:2]:
            print(f"  item id={item['id']}, file={item.get('file')}")
