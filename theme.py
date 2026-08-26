BLUE = "#2296D2"
BLUE_DARK = "#1475AA"
BLUE_LIGHT = "#173247"
GREEN = "#36D17E"
GREEN_DARK = "#21A963"
GREEN_LIGHT = "#16362B"
INK = "#EDF4FA"
MUTED = "#94A4B5"
BORDER = "#2C3947"
BG = "#11161C"
CARD = "#1A222C"

APP_QSS = r"""
* {
    font-family: "Segoe UI";
    font-size: 10pt;
    color: #EDF4FA;
}
QMainWindow, QWidget#Root {
    background: #11161C;
}
QFrame#Header {
    background: #0B1015;
    border-bottom: 1px solid #28333E;
}
QFrame#Footer {
    background: #0B1015;
    border-top: 1px solid #28333E;
}
QFrame#Card, QFrame#LocalCard, QFrame#RemoteCard {
    background: #1A222C;
    border: 1px solid #2C3947;
    border-radius: 10px;
}
QFrame#RemoteCard {
    background: #18232D;
    border: 1px solid #315D7A;
}
QFrame#IdentityField {
    background: #101820;
    border: 1px solid #2D3C49;
    border-radius: 7px;
}
QFrame#AccessSecurity {
    background: #132A38;
    border: 1px solid #234B63;
    border-radius: 7px;
}
QFrame#ActiveSessions {
    background: #143047;
    border: 1px solid #2B6388;
    border-radius: 8px;
}
QFrame#RecentRow {
    background: #172431;
    border: 1px solid #2D4051;
    border-radius: 8px;
}
QFrame#Tip {
    background: #161E27;
    border: 1px solid #2B3946;
    border-radius: 8px;
}
QScrollArea#DashboardScroll {
    background: #11161C;
    border: 0px;
}
QScrollArea#DashboardScroll > QWidget > QWidget {
    background: #11161C;
}
QScrollBar:vertical {
    background: #11161C;
    width: 10px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #344554;
    border-radius: 5px;
    min-height: 34px;
}
QScrollBar::handle:vertical:hover {
    background: #486174;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0px;
}
QLabel#AppTitle {
    color: #F4F8FB;
    font-size: 20pt;
    font-weight: 700;
}
QLabel#BrandSubtitle {
    color: #8293A5;
    font-size: 9.5pt;
}
QLabel#HeaderEyebrow, QLabel#FieldEyebrow {
    color: #75889B;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#PageTitle {
    color: #F4F8FB;
    font-size: 17pt;
    font-weight: 700;
}
QLabel#PageSubtitle, QLabel#CardDescription {
    color: #91A2B3;
    font-size: 9.5pt;
}
QLabel#SecureBadge {
    color: #58E39A;
    background: #153328;
    border: 1px solid #255C43;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 9pt;
    font-weight: 600;
}
QLabel#CardTitle, QLabel#SectionTitle {
    color: #EFF6FB;
    font-weight: 700;
}
QLabel#CardTitle {
    font-size: 12.5pt;
}
QLabel#SectionTitle {
    font-size: 11.5pt;
}
QLabel#AvailabilityBadge {
    color: #58E39A;
    background: #153328;
    border: 1px solid #255C43;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#PrimaryBadge {
    color: #70C8F2;
    background: #173247;
    border: 1px solid #2B6689;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#FieldLabel {
    color: #A9B7C5;
    font-size: 9pt;
    font-weight: 600;
}
QLabel#LocalValue {
    color: #52C8FF;
    font-family: "Segoe UI Semibold";
    font-size: 25pt;
    font-weight: 700;
    letter-spacing: 2px;
}
QLabel#PinValue {
    color: #E7F1F8;
    font-family: "Segoe UI Semibold";
    font-size: 20pt;
    font-weight: 700;
    letter-spacing: 3px;
}
QLabel#IncomingStatus {
    color: #58E39A;
    font-size: 9pt;
    font-weight: 600;
}
QLabel#SecurityIcon {
    color: #52C8FF;
    font-size: 11pt;
    font-weight: 700;
}
QLabel#SecurityText {
    color: #A1B2C1;
    font-size: 8.5pt;
}
QLabel#StatusOnline {
    color: #58E39A;
    background: #153328;
    border: 1px solid #255C43;
    border-radius: 7px;
    padding: 6px 10px;
    font-size: 9pt;
    font-weight: 600;
}
QLabel#StatusOffline {
    color: #FF8C8C;
    background: #3A1E22;
    border: 1px solid #663238;
    border-radius: 7px;
    padding: 6px 10px;
    font-size: 9pt;
    font-weight: 600;
}
QLabel#StatusOptional {
    color: #9DAEBE;
    background: #171F28;
    border: 1px solid #303D49;
    border-radius: 7px;
    padding: 6px 10px;
    font-size: 9pt;
    font-weight: 600;
}
QLabel#ActiveSessionsIcon {
    color: #52C8FF;
    font-size: 17pt;
    font-weight: 700;
}
QLabel#ActiveSessionsTitle {
    color: #71CDF7;
    font-weight: 700;
}
QLabel#SessionTitleOnline {
    color: #58E39A;
    font-size: 10.5pt;
    font-weight: 700;
}
QLabel#SessionCount {
    color: #A5B4C2;
    background: #17212A;
    border: 1px solid #33414E;
    border-radius: 7px;
    padding: 5px 9px;
    font-size: 8.5pt;
    font-weight: 600;
}
QLabel#RecentIcon {
    color: #73CEF8;
    background: #19384E;
    border: 1px solid #2B6588;
    border-radius: 7px;
    font-size: 8pt;
    font-weight: 700;
}
QLabel#RecentName {
    color: #F2F7FA;
    font-size: 10pt;
    font-weight: 700;
}
QLabel#RecentMeta, QLabel#Muted {
    color: #899BAC;
    font-size: 9pt;
}
QLabel#TipIcon {
    color: #FFFFFF;
    background: #1689C2;
    border-radius: 9px;
    min-width: 18px;
    max-width: 18px;
    min-height: 18px;
    max-height: 18px;
    font-family: "Segoe UI Semibold";
    font-size: 9pt;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}
QLabel#TipText, QLabel#FooterSecurity {
    color: #91A2B3;
    font-size: 9pt;
}
QLabel#FooterVersion {
    color: #6F8192;
    font-size: 8.5pt;
}
QLineEdit {
    color: #F2F7FA;
    background: #0D141B;
    border: 1px solid #384956;
    border-radius: 7px;
    padding: 9px 11px;
    min-height: 20px;
    selection-background-color: #1689C2;
}
QLineEdit:hover {
    border-color: #547084;
}
QLineEdit:focus {
    border: 2px solid #2296D2;
    padding: 8px 10px;
}
QPushButton {
    color: #DDE8F0;
    background: #202B35;
    border: 1px solid #3A4957;
    border-radius: 7px;
    padding: 8px 13px;
    font-weight: 600;
}
QPushButton:hover {
    color: #FFFFFF;
    background: #293743;
    border-color: #587082;
}
QPushButton:pressed {
    background: #141C23;
}
QPushButton:disabled {
    color: #637280;
    background: #171E25;
    border-color: #28333D;
}
QPushButton#Primary, QPushButton#PrimaryCompact {
    color: #FFFFFF;
    background: #1689C2;
    border-color: #1689C2;
}
QPushButton#Primary {
    min-height: 23px;
    font-size: 10.5pt;
}
QPushButton#Primary:hover, QPushButton#PrimaryCompact:hover {
    background: #1B9AD6;
    border-color: #1B9AD6;
}
QPushButton#Secondary {
    color: #AFC0CE;
    background: #161E26;
    border-color: #303C47;
}
QPushButton#Ghost, QPushButton#FooterButton {
    color: #90A2B2;
    background: transparent;
    border-color: #33414D;
    padding: 7px 11px;
    font-size: 9pt;
}
QPushButton#RecentAction {
    color: #70C8F2;
    background: #132330;
    border-color: #2A5975;
    padding: 6px 10px;
    font-size: 9pt;
}
QPushButton#RecentAction:hover {
    color: #FFFFFF;
    background: #174260;
    border-color: #34779E;
}
QPushButton#ViewMode {
    color: #9EB0C0;
    background: #18212A;
    border-color: #34424E;
    padding: 8px 12px;
}
QPushButton#ViewMode:checked {
    color: #71CDF7;
    background: #173247;
    border-color: #2D6C92;
}
QPushButton#Danger {
    color: #FF9494;
    background: #352025;
    border-color: #63363D;
}
QPushButton#Danger:hover {
    background: #46272D;
}
QPushButton#CopyButton {
    color: #70C8F2;
    background: #182630;
    border-color: #344B5C;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 0px;
    font-size: 12pt;
}
QTabWidget::pane {
    background: #11161C;
    border: 0px;
    top: -1px;
}
QTabBar {
    background: #0B1015;
    border-bottom: 1px solid #2B3742;
}
QTabBar::tab {
    color: #8799AA;
    background: #171F27;
    border: 1px solid #303C48;
    border-bottom: 3px solid transparent;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 9px 17px;
    margin: 7px 2px 0px 6px;
}
QTabBar::tab:selected {
    color: #FFFFFF;
    background: #202A34;
    font-weight: 700;
    border-bottom: 3px solid #2296D2;
}
QTabBar::tab:hover {
    color: #FFFFFF;
    background: #23303B;
}
QWidget#SplitPage {
    background: #0D1217;
}
QProgressBar {
    background: #222E38;
    border: 0px;
    border-radius: 5px;
    min-height: 9px;
    text-align: center;
}
QProgressBar::chunk {
    background: #36D17E;
    border-radius: 5px;
}
QMessageBox, QFileDialog, QDialog {
    background: #171E26;
}
QToolTip {
    color: #FFFFFF;
    background: #21303C;
    border: 1px solid #3A4A57;
    padding: 6px;
}
"""
