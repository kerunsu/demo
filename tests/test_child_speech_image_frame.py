from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_demo_naming_uses_natural_ratio_frame_without_extra_courses():
    child = _read("static/js/child.js")
    framed = child[
        child.index("const FRAMED_SPEECH_IMAGE_COURSE_TYPES") :
        child.index("let resourceTransitionGeneration")
    ]

    assert '"naming"' in framed
    for disabled_type in ('"mimic"', '"onomatopoeia"', '"pairing"', '"social"'):
        assert disabled_type not in framed
    assert 'presentation: imagePresentationForCourse(payload, course)' in child
    assert "availableWidth / image.naturalWidth" in child
    assert "availableHeight / image.naturalHeight" in child
    assert "viewportHeight * (34 / 1080)" in child
    assert "frameWidth * 2" in child
    assert "return true;" in child[
        child.index("function layoutCourseImageFrame") :
        child.index("function applyCourseImagePresentation")
    ]
    assert "await waitForImageReady(staging, spec.src);" in child
    assert "applyCourseImagePresentation(staging, spec.presentation);" in child
    assert 'window.addEventListener("resize"' in child


def test_naming_image_frame_uses_background_palette_without_letterbox():
    css = _read("static/css/child.css")
    template = _read("templates/child.html")

    assert "--course-image-frame-color: #ffe38f" in css
    assert "#image.course-image-frame" in css
    assert "object-fit: fill" in css
    assert "box-shadow: 0 0 0 100vmax var(--course-image-frame-color)" in css
    assert "border-radius: var(--course-image-frame-radius)" in css
    assert "transform: translate(-50%, -50%)" in css
    assert 'child.css?v=20260826-child-surface-v2' in template
    assert 'child.js?v=20260828-behavior-terminal-fix-v1' in template
