from flask import Flask, send_from_directory
import os

app = Flask(__name__, static_folder="dist", static_url_path="/")

# 获取 dist 目录的绝对路径
DIST_DIR = os.path.join(os.path.dirname(__file__), "dist")

@app.route("/")
def index():
    """返回前端应用的 index.html"""
    return send_from_directory(DIST_DIR, "index.html")

@app.route("/<path:path>")
def serve_static(path):
    """处理所有静态资源请求（CSS、JS、图片等）"""
    return send_from_directory(DIST_DIR, path)

if __name__ == "__main__":
    # 开发模式运行
    app.run(debug=True, port=5000)

