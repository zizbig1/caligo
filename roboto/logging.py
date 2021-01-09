import logging
import colorlog

from datetime import datetime


def setup_log() -> None:
    """Configures logging"""
    level = logging.INFO

    logging.root.setLevel(level)

    # Logging into file
    format = "[ %(asctime)s:  %(levelname)s ]  %(name)s  |  %(message)s"
    logfile_name = f"roboto-{datetime.now().strftime('%Y-%m-%d')}.log"
    logfile = logging.FileHandler(f"roboto/{logfile_name}")
    formatter = logging.Formatter(format, datefmt="%H:%M:%S")
    logfile.setFormatter(formatter)
    logfile.setLevel(level)

    # Logging into stdout with color
    format = ("  %(log_color)s%(levelname)s%(reset)s  |  %(name)s  |  "
              "%(log_color)s%(message)s%(reset)s")
    stream = logging.StreamHandler()
    formatter = colorlog.ColoredFormatter(format)
    stream.setLevel(level)
    stream.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(logfile)
    root.addHandler(stream)
