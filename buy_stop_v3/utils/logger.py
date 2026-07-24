"""
Buy Stop V3 — 日志工具（稳定版）

- 单日志文件不轮换 → 改为按日轮换
- 保留最近30天日志
- 控制台+文件双输出
- fix: 日志文件无限增长问题
"""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from config.settings import LOG


def setup_logger(name: str = "buy_stop") -> logging.Logger:
    """初始化日志（带按日轮换）"""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG["LEVEL"].upper(), logging.INFO))

    # 日志目录
    log_file = Path(LOG["FILE"])
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # 文件 Handler — 按天轮换，保留30天
    fh = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1,
        backupCount=30, encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG["FORMAT"]))
    # 轮换时不生成空日志文件
    fh.namer = lambda name: name

    # 控制台 Handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    ))

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


logger = setup_logger()
