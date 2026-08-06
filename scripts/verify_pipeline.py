"""P1 验证脚本：跑通 N1–N5 全链路并输出结构化结果。

用法（在项目根目录）：
  # 离线样例（无密钥）
  python scripts/verify_pipeline.py --name "无线蓝牙耳机" --site SG --offline

  # 真实链路
  python scripts/verify_pipeline.py --name "无线蓝牙耳机" --site TH \
      --image 图1.png --image 图2.png --points "蓝牙5.3" --points "续航30小时" \
      --save-dir output
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import settings  # noqa: E402
from backend.pipeline import Pipeline  # noqa: E402
from backend.prompts import SITES  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="AetherForge N1–N5 链路验证")
    ap.add_argument("--image", action="append", default=[], help="商品图路径或 URL，可多次传入")
    ap.add_argument("--name", required=True, help="商品名称")
    ap.add_argument("--points", action="append", default=[], help="真实卖点，可多次传入")
    ap.add_argument("--site", default="SG", help="站点（8选1：SG/MY/TH/VN/PH/ID/TW/BR）")
    ap.add_argument("--offline", action="store_true", help="强制离线模式（不调用真实模型）")
    ap.add_argument("--save-dir", default="output", help="生成的图片保存目录")
    args = ap.parse_args()

    site = args.site.upper()
    if site not in SITES:
        print(f"[警告] 站点 {site} 不在支持列表 {list(SITES)}，继续尝试。")

    images = args.image
    if args.offline and not images:
        images = ["offline://sample.png"]

    pipe = Pipeline(offline=True if args.offline else None)
    result = pipe.run(images, args.name, args.points, site, save_dir=args.save_dir)

    print("=" * 60)
    print(f"status       : {result.status}")
    print(f"message      : {result.message}")
    print(f"identity_lock: {result.identity_lock}")
    print(f"standard     : {result.standard_product_image_url}")
    print(f"detail images: {len(result.result_image_urls)} 张")
    for i, url in enumerate(result.result_image_urls, start=1):
        print(f"  [{i}] {url}")
    if result.details.get("offline"):
        print("[离线模式] 未调用真实模型。")
    print("=" * 60)


if __name__ == "__main__":
    main()
