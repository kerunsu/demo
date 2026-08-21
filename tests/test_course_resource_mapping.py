import csv
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_onomatopoeia_resource_folders_match_animal_labels():
    mapping_file = PROJECT_ROOT / "config" / "course_items_mapping.csv"
    with mapping_file.open(encoding="utf-8", newline="") as handle:
        rows = {
            row["folder_id"]: row["name"]
            for row in csv.DictReader(handle)
            if row["course_type"] == "voice"
        }

    assert rows == {
        "201": "小猫叫",
        "202": "小牛叫",
        "203": "小狗叫",
        "204": "小鸭叫",
        "205": "小羊叫",
        "206": "小鸡叫",
        "207": "小老虎叫",
    }

    for folder_id in rows:
        folder = PROJECT_ROOT / "static" / "resources" / "images" / "voice" / folder_id
        assert folder.is_dir()
        assert any(path.is_file() for path in folder.iterdir())


def test_course_resource_import_uses_media_folder_as_stable_identity():
    source = (PROJECT_ROOT / "database" / "import_course_resources.py").read_text(
        encoding="utf-8"
    )

    assert "media_file=item_data['folder_path']" in source
    assert "existing_item.name = item_data['name']" in source
