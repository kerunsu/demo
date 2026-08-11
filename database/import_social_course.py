"""
导入社交课程到数据库（打招呼 / 再见）
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import db, Course, CourseItem, CourseType
from flask import Flask


def import_social_course(force: bool = False):
    """导入社交课程和课程项。force=True 时覆盖已有社交课程（非交互）。"""
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'app.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    with app.app_context():
        social_type = CourseType.query.filter_by(name='社交').first()
        if not social_type:
            social_type = CourseType(name='社交')
            db.session.add(social_type)
            db.session.flush()
            print(f"[ok] created course type social: id={social_type.id}")
        else:
            print(f"[ok] found course type social: id={social_type.id}")

        existing_course = Course.query.filter_by(
            course_type_id=social_type.id, title='社交课程'
        ).first()
        if existing_course:
            if not force:
                print(f"[warn] social course exists: id={existing_course.id}")
                print("pass --force to overwrite")
                return False
            db.session.delete(existing_course)
            db.session.commit()
            print("[ok] deleted existing social course")

        course = Course(
            course_type_id=social_type.id,
            title='社交课程',
            icon=None,
            question_audio=None,
            praise_audio=None,
            entry_file=None,
        )
        db.session.add(course)
        db.session.flush()
        print(f"[ok] created course: id={course.id}")

        items = [
            ('打招呼', 'greeting'),
            ('再见', 'farewell'),
        ]
        for name, role in items:
            item = CourseItem(
                course_id=course.id,
                name=name,
                type='image',
                media_file=None,
                icon=None,
                hint_audio=None,
                config=json.dumps({'socialRole': role}, ensure_ascii=False),
            )
            db.session.add(item)
            print(f"[ok] item: {name} socialRole={role}")

        db.session.commit()
        print("[done] social course imported")

        course = Course.query.filter_by(course_type_id=social_type.id, title='社交课程').first()
        print(f"Course: id={course.id}, title={course.title}")
        for item in course.items:
            print(f"  - id={item.id}, name={item.name}, config={item.config}")
        return True


if __name__ == '__main__':
    print("=" * 50)
    print("社交课程导入脚本")
    print("=" * 50)
    force = '--force' in sys.argv
    import_social_course(force=force)
