"""导出下载行为回归测试：中文 ZIP 文件名 header + 结果页下载控件。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT if (ROOT / "backend").is_dir() else Path("/app")))

from backend.routers.projects import _attachment_disposition


def main() -> None:
    header = _attachment_disposition("晾衣杆_20260807.zip")
    header.encode("latin-1")
    assert 'filename="' in header
    assert "filename*=UTF-8''%E6%99%BE%E8%A1%A3%E6%9D%86_20260807.zip" in header
    print("PASS: export download headers")


if __name__ == "__main__":
    main()
