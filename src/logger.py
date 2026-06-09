"""
Logging centralizado del proyecto.
"""
import logging
import sys
from datetime import datetime

from config.settings import LOG_DIR


def get_logger(name: str = "egov-audit") -> logging.Logger:
    """Devuelve un logger configurado, con salida a consola y archivo."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fname = LOG_DIR / f"egov-audit-{datetime.now().strftime('%Y%m%d')}.log"
    fh = logging.FileHandler(fname, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
