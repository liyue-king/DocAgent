"""
====================================================================
文件用途：ChromaDB 初始化脚本（灌入 10 条模板向量）
====================================================================
作用：
    1. 从 seed_templates.json 读取预设模板。
    2. 复用 app/services/template_seed.py 完成向量化 + ChromaDB
       upsert + MySQL templates 表回填（幂等）。
运行：
    PYTHONPATH=. python scripts/init_chroma.py
依赖：
    - ChromaDB 容器（localhost:8000）
    - MySQL 容器（localhost:3307，需先跑 init_db.py 建表）
    - BGE-M3 模型（首次运行自动下载 ~2GB）
====================================================================
"""

from __future__ import annotations

import json  # 读取种子模板 JSON
import sys  # 退出码
from pathlib import Path  # 跨平台路径

from app.db import SessionLocal  # MySQL 会话工厂
from app.services.template_seed import seed_templates  # 共用灌入逻辑


def init_chroma() -> int:
    """主流程：读取种子模板并灌入。返回 0=成功，1=失败。"""
    # ---------- 1. 读取种子模板 ----------
    seed_path = Path(__file__).resolve().parent / "seed_templates.json"
    with open(seed_path, encoding="utf-8") as f:
        seeds = json.load(f)
    print(f"读取 {len(seeds)} 条种子模板。")

    # ---------- 2. 向量化 + 灌入 + MySQL 回填 ----------
    db = SessionLocal()
    try:
        return seed_templates(db, seeds)
    except Exception as exc:  # 向量库/模型不可用等
        print(f"灌入失败: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(init_chroma())
