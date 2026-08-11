#!/usr/bin/env python3
"""
首次部署 / 环境体检（幂等）。

同学流程：
  1. git clone / pull
  2. python scripts/bootstrap.py
  3. 按提示启动：python app.py

已配好环境时再跑：只检查、缺什么补什么，不会无故覆盖 .env / 已有 app.db。

常用参数：
  --check-only          只报告，不安装/不建库
  --reset-db            删除 app.db 后重建并播种标准库（需 --yes）
  --seed-courses        在已有库上强制重跑标准库播种（覆盖课程）
  --skip-pip / --skip-npm
  --optional-analyzers  额外安装 requirements-optional-analyzers.txt
  --yes                 非交互确认（配合 --reset-db）
"""
from __future__ import annotations

import argparse
import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from packaging.requirements import Requirement
except ImportError:  # Fresh venvs may only expose pip's vendored copy.
    from pip._vendor.packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / '.venv'
DB_PATH = ROOT / 'database' / 'app.db'
ENV_PATH = ROOT / '.env'
ENV_EXAMPLE = ROOT / '.env.example'
REQ = ROOT / 'requirements.txt'
REQ_OPT = ROOT / 'requirements-optional-analyzers.txt'
FRONTEND = ROOT / 'teacher_frontend'
NODE_MODULES = FRONTEND / 'node_modules'


def _info(msg: str) -> None:
    print(f"[bootstrap] {msg}")


def _warn(msg: str) -> None:
    print(f"[bootstrap] WARN: {msg}")


def _ok(msg: str) -> None:
    print(f"[bootstrap] OK  {msg}")


def _fail(msg: str) -> None:
    print(f"[bootstrap] FAIL {msg}")


def venv_python() -> Path | None:
    if os.name == 'nt':
        p = VENV_DIR / 'Scripts' / 'python.exe'
    else:
        p = VENV_DIR / 'bin' / 'python'
    return p if p.is_file() else None


def project_python() -> Path:
    """优先 .venv，否则用当前解释器（兼容已用系统/conda 配好环境的同学）。"""
    return venv_python() or Path(sys.executable)


def run(cmd: list, cwd: Path | None = None, check: bool = True) -> int:
    _info(' '.join(str(c) for c in cmd))
    r = subprocess.run(cmd, cwd=str(cwd or ROOT))
    if check and r.returncode != 0:
        raise RuntimeError(f'command failed ({r.returncode}): {cmd}')
    return r.returncode


def check_python() -> bool:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        _fail(f'需要 Python 3.10+，当前 {major}.{minor}')
        return False
    _ok(f'Python {major}.{minor}')
    return True


def ensure_venv(check_only: bool) -> bool:
    if venv_python() is not None:
        _ok(f'venv 已存在: {VENV_DIR}')
        return True
    # 当前解释器已能跑项目时，不强制建 .venv
    probe = subprocess.run(
        [sys.executable, '-c', 'import flask, dotenv'],
        cwd=str(ROOT),
        capture_output=True,
    )
    if probe.returncode == 0:
        _ok(f'未使用 .venv，当前解释器可用: {sys.executable}')
        return True
    if check_only:
        _warn(f'缺少 venv: {VENV_DIR}（且当前 Python 无法 import flask）')
        return False
    _info(f'创建 venv → {VENV_DIR}')
    run([sys.executable, '-m', 'venv', str(VENV_DIR)])
    _ok('venv 已创建')
    return True


def _unsatisfied_requirements(paths: list[Path]) -> list[str]:
    missing: list[str] = []
    for path in paths:
        if not path.is_file():
            missing.append(f'missing_file:{path.name}')
            continue
        for raw in path.read_text(encoding='utf-8').splitlines():
            line = raw.split('#', 1)[0].strip()
            if not line or line.startswith(('-', '--')):
                continue
            try:
                requirement = Requirement(line)
            except Exception:
                missing.append(f'invalid_requirement:{line}')
                continue
            if requirement.marker and not requirement.marker.evaluate():
                continue
            try:
                installed = importlib.metadata.version(requirement.name)
            except importlib.metadata.PackageNotFoundError:
                missing.append(f'{requirement.name}:not_installed')
                continue
            if requirement.specifier and installed not in requirement.specifier:
                missing.append(
                    f'{requirement.name}:{installed} not in {requirement.specifier}'
                )
    return missing


def analyzers_require_optional() -> bool:
    override = os.environ.get('USE_REAL_ANALYZERS', '').strip().lower()
    if override in {'0', 'false', 'no', 'off'}:
        return False
    if override in {'1', 'true', 'yes', 'on'}:
        return True
    config = ROOT / 'config' / 'analyzers.yaml'
    if not config.is_file():
        return False
    try:
        import yaml

        payload = yaml.safe_load(config.read_text(encoding='utf-8')) or {}
        return str((payload.get('global') or {}).get('mode') or '').lower() == 'real'
    except Exception:
        return False


def _analyzer_import_probe(py: Path, optional: bool) -> tuple[bool, str]:
    imports = ['import flask, dotenv', 'from mediapipe import solutions']
    if optional:
        imports.append('import torch, torchaudio, funasr, modelscope, librosa')
    probe = subprocess.run(
        [str(py), '-c', '; '.join(imports)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    detail = (probe.stderr or probe.stdout or '').strip().splitlines()
    return probe.returncode == 0, (detail[-1] if detail else '')


def ensure_pip(check_only: bool, skip: bool, optional: bool) -> bool:
    if skip:
        _info('跳过 pip（--skip-pip）')
        return True
    py = project_python()
    requirement_files = [REQ] + ([REQ_OPT] if optional else [])
    unsatisfied = _unsatisfied_requirements(requirement_files)
    imports_ok, import_error = _analyzer_import_probe(py, optional)
    if not unsatisfied and imports_ok:
        _ok(f'Python 依赖版本与分析器导入均就绪（{py}）')
        return True
    if check_only:
        detail = ', '.join(unsatisfied[:8]) or import_error or 'import_probe_failed'
        _warn('Python 依赖不完整: ' + detail)
        return False
    if not REQ.is_file():
        _fail(f'找不到 {REQ}')
        return False
    if _unsatisfied_requirements([REQ]) or not imports_ok:
        run([str(py), '-m', 'pip', 'install', '-r', str(REQ)])
    if optional and REQ_OPT.is_file() and _unsatisfied_requirements([REQ_OPT]):
        _info('安装可选分析依赖（体积较大）')
        run([str(py), '-m', 'pip', 'install', '-r', str(REQ_OPT)])
    remaining = _unsatisfied_requirements(requirement_files)
    imports_ok, import_error = _analyzer_import_probe(py, optional)
    if remaining or not imports_ok:
        _fail('依赖安装后仍未就绪: ' + (', '.join(remaining[:8]) or import_error))
        return False
    _ok('pip 依赖已安装并通过导入验证')
    return True


def ensure_env(check_only: bool) -> bool:
    if ENV_PATH.is_file():
        _ok('.env 已存在（不会覆盖）')
        return True
    if not ENV_EXAMPLE.is_file():
        _warn('无 .env.example，跳过')
        return True
    if check_only:
        _warn('缺少 .env（可从 .env.example 复制）')
        return False
    shutil.copy2(ENV_EXAMPLE, ENV_PATH)
    _ok('已从 .env.example 复制 .env，请按需修改')
    return True


def ensure_npm(check_only: bool, skip: bool) -> bool:
    if skip:
        _info('跳过 npm（--skip-npm）')
        return True
    if not FRONTEND.is_dir():
        _warn('无 teacher_frontend，跳过')
        return True
    npm_cmd = shutil.which('npm')
    if npm_cmd is not None and NODE_MODULES.is_dir():
        probe = subprocess.run(
            [npm_cmd, 'ls', '--depth=0'],
            cwd=str(FRONTEND),
            capture_output=True,
        )
    else:
        probe = None
    if probe is not None and probe.returncode == 0:
        _ok('teacher_frontend 依赖树与 package.json 一致')
        return True
    if check_only:
        _warn('缺少 teacher_frontend/node_modules')
        return False
    if npm_cmd is None:
        _fail('未找到 npm，请先安装 Node.js LTS')
        return False
    lock = FRONTEND / 'package-lock.json'
    cmd = [npm_cmd, 'ci'] if lock.is_file() else [npm_cmd, 'install']
    run(cmd, cwd=FRONTEND)
    _ok('前端依赖已安装')
    return True


def ensure_resources(check_only: bool) -> bool:
    """课程媒体应在 Git 中；此处只做体检。"""
    checks = [
        ROOT / 'static' / 'resources' / 'audios',
        ROOT / 'static' / 'resources' / 'images',
        ROOT / 'static' / 'resources' / 'interactive' / 'matching.html',
        ROOT / 'static' / 'resources' / 'interactive' / 'sequencing.html',
        ROOT / 'static' / 'courses.json',
        ROOT / 'config' / 'course_items_mapping.csv',
        ROOT / 'config' / 'audio_manifest.yaml',
    ]
    missing = [str(p.relative_to(ROOT)) for p in checks if not p.exists()]
    if missing:
        _warn('缺少资源/配置（应通过 git pull 获得）: ' + ', '.join(missing))
        return False
    _ok('课程资源与关键配置文件存在')
    return True


def ensure_db(
    check_only: bool,
    reset_db: bool,
    seed_courses: bool,
    yes: bool,
) -> bool:
    py = project_python()

    if reset_db:
        if check_only:
            _warn('将删除并重建 app.db（check-only 未执行）')
            return False
        if not yes:
            _fail('--reset-db 需要同时传 --yes')
            return False
        if DB_PATH.is_file():
            DB_PATH.unlink()
            _info('已删除 database/app.db')
        seed_courses = True

    if not DB_PATH.is_file():
        if check_only:
            _warn('缺少 database/app.db（首次应 init + 标准库播种）')
            return False
        _info('无 app.db → 运行标准库播种')
        run([str(py), str(ROOT / 'database' / 'seed_standard.py')])
        _ok('标准库已创建')
        return True

    _ok('database/app.db 已存在（默认不重建）')
    if seed_courses:
        if check_only:
            _warn('将强制重播标准库课程（check-only 未执行）')
            return True
        _info('强制重播标准库课程（--seed-courses）')
        run([str(py), str(ROOT / 'database' / 'seed_standard.py')])
        _ok('标准库课程已覆盖更新')
        return True

    # 已有库但缺社交课：只补齐，不整库覆盖（社交不在旧 courses.json 里，易漏）
    if _db_missing_social_course(py):
        if check_only:
            _warn('已有 app.db 但缺少「社交课程」，需补齐')
            return False
        _info('检测到缺少社交课程 → 运行 import_social_course --force')
        run([str(py), str(ROOT / 'database' / 'import_social_course.py'), '--force'])
        _ok('社交课程已补齐')
    return True


def _db_missing_social_course(py: Path) -> bool:
    """True = 库在但没有社交课程（或查库失败时偏保守地返回 False）。"""
    probe = r"""
import os, sys
sys.path.insert(0, os.getcwd())
from flask import Flask
from database.models import db, Course, CourseType
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join('database', 'app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
with app.app_context():
    t = CourseType.query.filter_by(name='社交').first()
    if not t:
        raise SystemExit(2)
    c = Course.query.filter_by(course_type_id=t.id).first()
    raise SystemExit(0 if c else 2)
"""
    r = subprocess.run([str(py), '-c', probe], cwd=str(ROOT), capture_output=True)
    return r.returncode == 2


def print_next_steps() -> None:
    py = project_python()
    print()
    print('=' * 60)
    print('下一步')
    print('=' * 60)
    if venv_python() is not None:
        if os.name == 'nt':
            print('  激活 venv:  .\\.venv\\Scripts\\Activate.ps1')
        else:
            print('  激活 venv:  source .venv/bin/activate')
    print(f'  启动项目:  {py} app.py')
    print('  儿童端:    http://127.0.0.1:8080/child')
    print('  教师端:    http://127.0.0.1:8080/teacher/  （Server 同源）')
    print('  默认账号:  admin / admin123')
    print('=' * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description='项目首次部署 / 环境体检（幂等）')
    parser.add_argument('--check-only', action='store_true', help='只检查不修改')
    parser.add_argument('--reset-db', action='store_true', help='删除 app.db 并重建标准库')
    parser.add_argument('--seed-courses', action='store_true', help='强制重跑标准库播种')
    parser.add_argument('--skip-pip', action='store_true')
    parser.add_argument('--skip-npm', action='store_true')
    parser.add_argument('--optional-analyzers', action='store_true')
    parser.add_argument('--yes', action='store_true', help='非交互确认')
    args = parser.parse_args()

    os.chdir(ROOT)
    _info(f'项目根目录: {ROOT}')

    optional_analyzers = bool(args.optional_analyzers or analyzers_require_optional())
    if optional_analyzers and not args.optional_analyzers:
        _info('检测到 analyzers.yaml 为 real，自动纳入真实分析器依赖')

    results = []
    results.append(('python', check_python()))
    results.append(('venv', ensure_venv(args.check_only)))
    results.append(('pip', ensure_pip(args.check_only, args.skip_pip, optional_analyzers)))
    results.append(('env', ensure_env(args.check_only)))
    results.append(('npm', ensure_npm(args.check_only, args.skip_npm)))
    results.append(('resources', ensure_resources(args.check_only)))
    results.append((
        'database',
        ensure_db(args.check_only, args.reset_db, args.seed_courses, args.yes),
    ))

    print()
    _info('汇总:')
    failed = []
    for name, ok in results:
        print(f'  {"OK " if ok else "MISS"}  {name}')
        if not ok:
            failed.append(name)

    if failed:
        _fail('未就绪: ' + ', '.join(failed))
        if args.check_only:
            _info('（当前为 --check-only，请去掉该参数后重新运行以自动补齐）')
        return 1

    _ok('全部检查通过')
    if not args.check_only:
        print_next_steps()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        _fail(str(e))
        raise SystemExit(1)
