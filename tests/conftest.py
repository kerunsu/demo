"""测试环境的轻量依赖兼容。生产运行仍使用 requirements.txt 中的真实包。"""
import sys
import types


try:
    import flask_socketio  # noqa: F401
except ModuleNotFoundError:
    module = types.ModuleType("flask_socketio")

    class SocketIO:  # pragma: no cover - 仅用于让纯逻辑单测完成模块导入
        def __init__(self, *args, **kwargs):
            pass

    module.SocketIO = SocketIO
    sys.modules["flask_socketio"] = module

try:
    import soundfile  # noqa: F401
except ModuleNotFoundError:
    # 纯逻辑测试不会执行音频文件读写，只需允许模块完成导入。
    soundfile_module = types.ModuleType("soundfile")
    soundfile_module.write = lambda *args, **kwargs: None
    sys.modules["soundfile"] = soundfile_module
