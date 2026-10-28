"""cli：命令解析、人话/JSON 渲染、错误码。

命令实现在阶段 A-03（池件 #10847）接线；本模块先提供 console-script 入口
占位，防止发布前脚本名被占用。
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    print("pool: 核心命令尚未实现（阶段 A-03），见 docs/product/design-v1.md §5", file=sys.stderr)
    return 2
