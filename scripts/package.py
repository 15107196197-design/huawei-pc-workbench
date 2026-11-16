"""Create a source-only delivery archive; credentials and runtime data never enter it."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
output = root / "output"
output.mkdir(exist_ok=True)
archive = output / "huawei-pc-agent-source.zip"
directories = ["huawei_agent", "static", "dify", "docs", "scripts", "tests", "review-site", "deploy"]
files = ["README.md", "pyproject.toml", "uv.lock", "requirements.lock", ".env.example", ".gitignore", ".dockerignore", "Dockerfile", "compose.yml", "启动工作台.command"]
with ZipFile(archive, "w", ZIP_DEFLATED) as z:
    for name in files:
        p = root / name
        if p.is_file(): z.write(p, name)
    for directory in directories:
        for p in sorted((root / directory).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                z.write(p, p.relative_to(root))
print(archive)
