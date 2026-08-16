"""抖音助手 — 程序入口。

用法: python main.py
"""
import sys
from pathlib import Path

# 内嵌 Python 用 ._pth 隔离模式，不会自动把脚本目录加入 sys.path，
# 这里手动加入项目目录，确保能导入 bot / gui 包。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from bot.config import Config
from gui.main_window import MainWindow

PROJECT_DIR = Path(__file__).resolve().parent

# 抖音配色主题（暗色 + 抖音红 #FE2C55）
STYLE_SHEET = """
QWidget { background-color: #1E1E24; color: #E8E8E8; font-size: 13px; }
QMainWindow { background-color: #161823; }
QLabel { background: transparent; color: #C8C8D0; }
QPushButton {
    background-color: #FE2C55; color: #FFFFFF; border: none;
    border-radius: 6px; padding: 8px 18px; font-weight: bold;
}
QPushButton:hover { background-color: #FF4D6E; }
QPushButton:pressed { background-color: #E01B44; }
QPushButton:disabled { background-color: #55555E; color: #999999; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #2A2A33; border: 1px solid #3A3A44; border-radius: 5px;
    padding: 6px 8px; color: #F0F0F5; selection-background-color: #FE2C55;
}
QListWidget { background-color: #23232B; border: 1px solid #3A3A44; border-radius: 6px; }
QListWidget::item { padding: 7px 10px; border-radius: 4px; }
QListWidget::item:selected { background-color: #FE2C55; color: #FFFFFF; }
QTabWidget::pane { border: 1px solid #3A3A44; border-radius: 6px; top: -1px; }
QTabBar::tab {
    background: #2A2A33; color: #BBBBBB; padding: 9px 18px;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}
QTabBar::tab:selected { background: #FE2C55; color: #FFFFFF; }
QCheckBox { color: #DDDDDD; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #555555; border-radius: 4px; background: #2A2A33; }
QCheckBox::indicator:checked { background: #FE2C55; border-color: #FE2C55; }
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button { border: none; }
QScrollBar:vertical { background: #23232B; width: 10px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #4A4A55; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #5A5A66; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("抖音助手")
    app.setOrganizationName("douyin-assistant")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE_SHEET)
    icon_path = PROJECT_DIR / "assets" / "douyin.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    cfg_path = PROJECT_DIR / "config.json"
    config = Config(cfg_path)
    if not cfg_path.exists():
        config.save()
    win = MainWindow(config)
    if icon_path.exists():
        win.setWindowIcon(QIcon(str(icon_path)))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
