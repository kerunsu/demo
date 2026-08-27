from app.monitor.snapshot import _build_connection_summary


def test_connection_summary_is_operator_facing():
    summary = _build_connection_summary({
        "teacherOnline": 1,
        "childOnline": 1,
        "connections": {
            "teacher": [{"ip": "192.168.1.20"}],
            "child": [{"ip": "192.168.1.106", "studentId": 2}],
        },
    }, None)
    cards = {card["id"]: card for card in summary["cards"]}
    assert cards["teacher"]["level"] == "ok"
    assert "192.168.1.20" in cards["teacher"]["summary"]
    assert "192.168.1.106" in cards["child"]["summary"]
    assert "runtime" not in cards
    assert summary["issues"] == []


def test_connection_summary_explains_duplicate_connections():
    summary = _build_connection_summary({
        "teacherOnline": 2,
        "childOnline": 0,
        "connections": {"teacher": [{}, {}], "child": []},
    }, None)
    problems = " ".join(item["problem"] for item in summary["issues"])
    assert "2 条教师连接" in problems
    assert "未连接儿童端" in problems
    assert "Runtime" not in problems
