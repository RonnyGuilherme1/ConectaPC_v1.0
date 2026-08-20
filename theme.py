BLUE = "#0B79C9"
BLUE_DARK = "#075C9C"
BLUE_LIGHT = "#EAF5FD"
GREEN = "#35C85B"
GREEN_DARK = "#17823A"
GREEN_LIGHT = "#ECFAF0"
INK = "#152033"
MUTED = "#6A778B"
BORDER = "#D8E2EC"
BG = "#F5F8FB"
CARD = "#FFFFFF"

APP_QSS = r"""
* {
    font-family: "Segoe UI";
    font-size: 10pt;
    color: #152033;
}
QMainWindow, QWidget#Root {
    background: #F5F8FB;
}
QFrame#Header {
    background: #FFFFFF;
    border-bottom: 1px solid #E5ECF2;
}
QFrame#Card {
    background: #FFFFFF;
    border: 1px solid #D8E2EC;
    border-radius: 16px;
}
QFrame#LocalCard {
    background: #F8FFFA;
    border: 1px solid #BFE8CA;
    border-radius: 16px;
}
QFrame#RemoteCard {
    background: #F8FBFF;
    border: 1px solid #C9DFF5;
    border-radius: 16px;
}
QFrame#Footer {
    background: #FFFFFF;
    border-top: 1px solid #E5ECF2;
}
QLabel#AppTitle {
    font-size: 22pt;
    font-weight: 700;
    color: #0B5F9E;
}
QLabel#CardTitle {
    font-size: 13pt;
    font-weight: 700;
}
QLabel#SectionTitle {
    font-size: 12pt;
    font-weight: 700;
}
QLabel#Muted {
    color: #6A778B;
}
QLabel#LocalValue {
    font-family: "Segoe UI Semibold";
    font-size: 27pt;
    font-weight: 700;
    color: #17823A;
    letter-spacing: 2px;
}
QLabel#PinValue {
    font-family: "Segoe UI Semibold";
    font-size: 22pt;
    font-weight: 700;
    color: #17823A;
    letter-spacing: 2px;
}
QLabel#StatusOnline {
    color: #137733;
    background: #EAF9EE;
    border: 1px solid #BDE8C8;
    border-radius: 12px;
    padding: 7px 12px;
    font-weight: 600;
}
QLabel#StatusOffline {
    color: #A33A3A;
    background: #FFF1F1;
    border: 1px solid #F0C7C7;
    border-radius: 12px;
    padding: 7px 12px;
    font-weight: 600;
}
QLineEdit {
    background: #FFFFFF;
    border: 1px solid #CAD6E2;
    border-radius: 10px;
    padding: 10px 12px;
    min-height: 20px;
}
QLineEdit:hover {
    border-color: #AFC3D5;
}
QLineEdit:focus {
    border: 2px solid #0B79C9;
    padding: 9px 11px;
}
QPushButton {
    background: #FFFFFF;
    border: 1px solid #C9D6E2;
    border-radius: 10px;
    padding: 9px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background: #F4F8FC;
    border-color: #AFC1D2;
}
QPushButton:pressed {
    background: #EAF1F7;
}
QPushButton#Primary {
    background: #0B79C9;
    color: #FFFFFF;
    border: 1px solid #0B79C9;
    font-size: 11pt;
    min-height: 24px;
}
QPushButton#Primary:hover {
    background: #086DB5;
}
QPushButton#Primary:pressed {
    background: #075C9C;
}
QPushButton#Danger {
    color: #B33A3A;
    background: #FFF8F8;
    border-color: #E6C7C7;
}
QPushButton#Danger:hover {
    background: #FFF0F0;
}
QPushButton#CopyButton {
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    padding: 0px;
    font-size: 13pt;
}
QPushButton:disabled {
    color: #A8B2BE;
    background: #F4F6F8;
    border-color: #E1E6EA;
}
QTabWidget::pane {
    background: #FFFFFF;
    border: 1px solid #D8E2EC;
    border-radius: 14px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #66758A;
    border: none;
    border-bottom: 3px solid transparent;
    padding: 10px 16px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    color: #0B79C9;
    font-weight: 700;
    border-bottom: 3px solid #0B79C9;
}
QTabBar::tab:hover {
    color: #0B79C9;
}
QProgressBar {
    background: #EDF2F6;
    border: 0px;
    border-radius: 6px;
    text-align: center;
    min-height: 10px;
}
QProgressBar::chunk {
    background: #35C85B;
    border-radius: 6px;
}
QMessageBox, QFileDialog {
    background: #FFFFFF;
}
QToolTip {
    color: #FFFFFF;
    background: #152033;
    border: 0px;
    padding: 6px;
}
"""
