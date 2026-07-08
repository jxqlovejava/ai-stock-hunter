# -*- coding: utf-8 -*-
"""白泽 (Baize) — A 股智能投资决策系统。

用法:
  python -m src                  # 打印帮助
  python -m src --help           # 同上
  python -m src diagnose 600519  # 一键诊断（推荐首次使用）
  python -m src analyze 600519   # 单只股票全链路分析
  python -m src scan             # 全市场选股
  python -m src macro            # 宏观快照

提示: 首次使用请运行 ./setup.sh 完成环境初始化。
"""

from src.cli import main

if __name__ == "__main__":
    main()
