import threading
import struct
import time
import math
import sys

from PyQt4.QtGui import *
from PyQt4.QtCore import *

from ..packet_flow import SocketController, SocketMode, KeyManager
from ..config import *
from ..opcodes import *
from ..audio import AudioIO, AudioProcessor


CLEAR_SCROLL = """
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollArea > QWidget > QScrollBar { background: palette(base); }
"""

POW_2 = math.pow(2, (5 / 6)) / 2


def db_to_thresh(db):
    # 24576 is a magic number from ((1 << 14) + (1 << 15)) / 2
    return 24576 * math.pow(POW_2, -db)

def thresh_to_db(thresh):
    if thresh == 0:
        return -68
    return (6 * math.log(abs(thresh))) / math.log(2) - 80


class SocketManager:
    sock = SocketController()

    km = KeyManager()
    client_sock = SocketController(km=km)
    udp_send = SocketController(SocketMode.UDP, km=km)
    udp_recv = SocketController(SocketMode.UDP, km=km)

    aio = AudioIO()
    amps = {}

    class AudioReturn(AudioProcessor):
        DECAY = 0.95

        def __init__(self, amps):
            self.amps = amps

        def process(self, data, packet, amp):
            #samps = struct.unpack('!{}h'.format(len(data) // 2), data)
            #avg = sum(map(abs, samps)) / len(samps)
            avg = amp
            if packet.client_id not in self.amps:
                self.amps[packet.client_id] = avg
            else:
                self.amps[packet.client_id] = self.amps[packet.client_id] * (1 - self.DECAY) + avg * self.DECAY
            return None

        def clone(self):
            return self.__class__(self.amps)

    @classmethod
    def mainloop(cls):
        while True:
            pkt = cls.udp_recv.get_packet(True)

            if pkt[2].opcode == AUDIO:
                cls.aio.feed(pkt[2].payload, pkt[2])

    @classmethod
    def setup(cls):
        cls.sock.connect(SERVER, CONTROL_PORT)
        cls.sock.start()
        cls.sock.do_tcp_client_auth()

        cls.client_sock.connect(SERVER, TCP_PORT)
        cls.client_sock.start()

        cls.client_id = cls.client_sock.do_tcp_client_auth()
        cls.udp_send.client_id = cls.client_id
        cls.udp_recv.client_id = cls.client_id

        cls.udp_send.connect(SERVER, TCP_PORT)

        cls.udp_recv.bind('', 0)
        cls.udp_port = cls.udp_recv.getsockname()[1]
        cls.udp_recv.start()

        reg_udp = struct.pack('!H', cls.udp_port)
        cls.client_sock.send_packet(REGISTER_UDP, reg_udp)

        cls.aio.back_pipeline.append(cls.AudioReturn(cls.amps))
        cls.aio.begin()

        threading.Thread(target=cls.mainloop, daemon=True).start()


class HBox(QWidget):
    def __init__(self, parent, align=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self.setLayout(self._layout)

        if align:
            self._layout.setAlignment(align)

    def addWidget(self, child):
        self._layout.addWidget(child)

    def setContentsMargins(self, *args):
        self._layout.setContentsMargins(*args)


class VBox(QWidget):
    def __init__(self, parent, align=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self.setLayout(self._layout)

        if align:
            self._layout.setAlignment(align)

    def addWidget(self, child):
        self._layout.addWidget(child)

    def setContentsMargins(self, *args):
        self._layout.setContentsMargins(*args)


class Spoiler(QWidget):
    def __init__(self, title, animationDuration, parent):
        super().__init__(parent)
        self.animationDuration = animationDuration

        self.toggleButton = QToolButton()
        self.toggleButton.setStyleSheet("QToolButton { border: none; }")
        self.toggleButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggleButton.setArrowType(Qt.RightArrow)
        self.toggleButton.setText(title)
        self.toggleButton.setCheckable(False)
        self.toggleButton.setChecked(False)

        self._open = False

        headerLine = QFrame()
        headerLine.setFrameShape(QFrame.HLine)
        headerLine.setFrameShadow(QFrame.Sunken)
        headerLine.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.contentArea = QScrollArea()
        self.contentArea.setStyleSheet(CLEAR_SCROLL)
        self.contentArea.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Start out collapsed
        self.contentArea.setMaximumHeight(0)
        self.contentArea.setMinimumHeight(0)
        # Let the entire widget grow and shrink with its content
        self.toggleAnimation = QParallelAnimationGroup()
        self.toggleAnimation.addAnimation(QPropertyAnimation(self, "minimumHeight"))
        self.toggleAnimation.addAnimation(QPropertyAnimation(self, "maximumHeight"))
        self.toggleAnimation.addAnimation(QPropertyAnimation(self.contentArea, "maximumHeight"))
        # Don't waste space
        mainLayout = QGridLayout()
        mainLayout.setVerticalSpacing(0)
        mainLayout.setContentsMargins(0, 0, 0, 0)

        row = 0
        mainLayout.addWidget(self.toggleButton, row, 0, 1, 1, Qt.AlignLeft)
        mainLayout.addWidget(headerLine, row, 2, 1, 1);
        row += 1
        mainLayout.addWidget(self.contentArea, row, 0, 1, 3);

        self.setLayout(mainLayout)
        self.toggleButton.clicked.connect(self.on_click)

    def open(self):
        if not self._open:
            self.on_click()

    def close(self):
        if self._open:
            self.on_click()

    def on_click(self):
        self._open = not self._open
        checked = self._open

        self.toggleButton.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.toggleAnimation.setDirection(QAbstractAnimation.Forward if checked else QAbstractAnimation.Backward)
        self.toggleAnimation.start()

    def setContentLayout(self, contentLayout):
        self.contentArea.setLayout(contentLayout)
        self.reloadContentLayout()

    def reloadContentLayout(self):
        collapsedHeight = self.sizeHint().height() - self.contentArea.maximumHeight()
        contentHeight = self.contentArea.layout().sizeHint().height()

        for i in range(self.toggleAnimation.animationCount() - 1):

            spoilerAnimation = self.toggleAnimation.animationAt(i)
            spoilerAnimation.setDuration(self.animationDuration)
            spoilerAnimation.setStartValue(collapsedHeight)
            spoilerAnimation.setEndValue(collapsedHeight + contentHeight)

        contentAnimation = self.toggleAnimation.animationAt(self.toggleAnimation.animationCount() - 1)
        contentAnimation.setDuration(self.animationDuration)
        contentAnimation.setStartValue(0)
        contentAnimation.setEndValue(contentHeight)


class VBSpoiler(Spoiler):
    def __init__(self, *args):
        super().__init__(*args)

        self._layout = QVBoxLayout()

        self.setContentLayout(self._layout)

    def addWidget(self, widget):
        self._layout.addWidget(widget)
        self.reloadContentLayout()


class HBSpoiler(Spoiler):
    def __init__(self, *args):
        super().__init__(*args)

        self._layout = QHBoxLayout()

        self.setContentLayout(self._layout)

    def addWidget(self, widget):
        self._layout.addWidget(widget)
        self.reloadContentLayout()


class MetadataListModel(QAbstractListModel):
    MetadataRole = Qt.UserRole

    MaxRole = MetadataRole

    def __init__(self, source=False):
        super().__init__()
        self.listdata = []
        self.tooltips = []
        self.metadata = []

        self.source = source

        self.setSupportedDragActions(Qt.CopyAction if self.source else Qt.MoveAction)
        self.sort(0)

    # Curstom methods
    def addItem(self, text, tooltip=None, metadata=None):
        self.listdata.append(text)
        self.tooltips.append(tooltip)
        self.metadata.append(metadata)
        self.sort(0)

    # QAbstractListModel overrides
    def rowCount(self, parent=QModelIndex()):
        return len(self.listdata)

    def data(self, index, role=Qt.DisplayRole):
        self.sort(0)

        if index.isValid():
            row = index.row()
            if row >= len(self.listdata):
                return None

            if role == Qt.DisplayRole:
                return self.listdata[index.row()]
            if role == Qt.ToolTipRole:
                return self.tooltips[index.row()]
            if role == self.MetadataRole:
                return self.metadata[index.row()]
        return None

    def removeRows(self, row, count, parent):
        self.beginRemoveRows(parent, row, row + count -1)
        self.listdata = self.listdata[:row] + self.listdata[row + count:]
        self.tooltips = self.tooltips[:row] + self.tooltips[row + count:]
        self.metadata = self.metadata[:row] + self.metadata[row + count:]
        self.endRemoveRows()
        return True

    def flags(self, index):
        if index.isValid():
            return Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsEnabled
        return Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled | Qt.ItemIsEnabled

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def columnCount(self, parent):
        return 0 if parent.isValid() else 1

    def dropMimeData(self, data, action, row, column, parent):
        encoded = data.data('application/x-qabstractitemmodeldatalist')
        stream = QDataStream(encoded, QIODevice.ReadOnly)
        return self.decodeData(row, column, parent, stream)

    def setItemData(self, index, roles):
        if Qt.DisplayRole in roles:
            self.listdata[index.row()] = roles[Qt.DisplayRole]
        if Qt.ToolTipRole in roles:
            self.tooltips[index.row()] = roles[Qt.ToolTipRole]
        if self.MetadataRole in roles:
            self.metadata[index.row()] = roles[self.MetadataRole]

        return True

    def sort(self, column, order=Qt.AscendingOrder):
        if not self.listdata:
            return

        new_l = []
        for i in zip(self.listdata, self.tooltips, self.metadata):
            if i not in new_l:
                new_l.append(i)

        self.listdata, self.tooltips, self.metadata = zip(*sorted(new_l))
        self.listdata = list(self.listdata)
        self.tooltips = list(self.tooltips)
        self.metadata = list(self.metadata)

    def insertRows(self, row, count, parent):
        self.beginInsertRows(parent, row, row + count -1)

        row = max(row, 0)
        self.listdata = self.listdata[:row] + [None] * count + self.listdata[row:]
        self.tooltips = self.tooltips[:row] + [None] * count + self.tooltips[row:]
        self.metadata = self.metadata[:row] + [None] * count + self.metadata[row:]
        self.endInsertRows()

        return True

    def itemData(self, index):
        roles = {}
        for i in range(self.MaxRole + 1):
            variantData = self.data(index, i);
            if variantData is not None:
                roles[i] = variantData
        return roles


class RoomsPane(QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(CLEAR_SCROLL)

        self.columns = HBox(self)
        self.scroll.setWidget(self.columns)

        self.add_column('All Clients', 0)
        self.add_column('Room #1', 1)
        self.add_column('Room #2', 2)
        self.add_column('Room #3', 3)

        self.layout.addWidget(self.scroll)

    def add_column(self, name, n, width=250):
        col = VBox(self.columns)
        col.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(name, col)
        heading.setFixedWidth(width)
        col.addWidget(heading)

        view = QListView()
        model = MetadataListModel(n == 0)
        view.setModel(model)
        view.setDragDropMode(QAbstractItemView.DragDrop)
        view.setDefaultDropAction(Qt.MoveAction)

        if n == 0:
            for _ in range(10):
                name = f'NO NAME ({_})'
                ip = f'192.168.0.{_ + 1}'
                mac = '00:11:22:33:44:55:66'
                model.addItem(name, f'Name: {name}\nIP: {ip}\nMAC: {mac}')

        col.addWidget(view)

        self.columns.addWidget(col)


class AudioChart(QWidget):
    BACKGROUND = QBrush(QColor(225, 250, 136))
    GRID_LINE1 = QColor(177, 198, 106)
    GRID_LINE2 = QColor(168, 190, 99)
    ZERO_LINE = QColor(82, 93, 48)
    TEXT_COLOR = QColor(82, 93, 48)
    DIAG_LINE = QColor(171, 196, 84)

    MAIN_LINE_C = QColor(89, 102, 51)
    MAIN_LINE = QPen(MAIN_LINE_C, 2)

    def __init__(self, parent, width=400, height=400):
        super().__init__(parent)
        self._size = (width, height)

        self.enabled = True
        self.blob = -12

        self.setFixedWidth(width)
        self.setFixedHeight(height)

    def paintEvent(self, event):
        qp = QPainter()
        qp.begin(self)

        qp.fillRect(0, 0, *self._size, self.BACKGROUND)
        cell_w = (self._size[0] - 1) / 16
        cell_h = (self._size[0] - 1) / 16

        # y = x
        qp.setPen(self.DIAG_LINE)
        qp.drawLine(-1, self._size[1], self._size[0], -1)

        # Minor lines
        qp.setPen(self.GRID_LINE1)
        for i in range(0, 18, 2):
            qp.drawLine(0, i * cell_h, self._size[0], i * cell_h)
            qp.drawLine(i * cell_w, 0, i * cell_w, self._size[1])
        # Major lines
        qp.setPen(self.GRID_LINE2)
        for i in range(1, 18, 2):
            qp.drawLine(0, i * cell_h, self._size[0], i * cell_h)
            qp.drawLine(i * cell_w, 0, i * cell_w, self._size[1])
        # Zero line
        qp.setPen(self.ZERO_LINE)
        qp.drawLine(0, 5 * cell_h, self._size[0], 5 * cell_h)
        qp.drawLine(11 * cell_w, 0, 11 * cell_w, self._size[1])

        # dB markers
        qp.setPen(self.TEXT_COLOR)
        qp.setFont(QFont('Decorative', 10))
        for i in range(1, 18, 2):
            rect = QRect(0, (i - 0.5) * cell_h, self._size[0] - 4, cell_h)
            qp.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, f'{(16 - i) * 6 - 66} dB')

        for i in range(3, 18, 4):
            rect = QRect((i - 1) * cell_w, self._size[1] - 50, cell_w * 2, 50)
            qp.drawText(rect, Qt.AlignHCenter | Qt.AlignBottom, f'{i * 6 - 66}')

        qp.setPen(self.MAIN_LINE)
        qp.setBrush(QBrush(self.MAIN_LINE_C, Qt.SolidPattern))
        b_x, b_y = self.getBlob()

        qp.setRenderHint(QPainter.Antialiasing)
        qp.drawEllipse(b_x - 4, b_y - 4, 8, 8)
        self.drawMain(qp)

        if not self.enabled:
            qp.fillRect(QRect(0, 0, *self._size), QBrush(QColor(240, 240, 240, 90)))

        qp.end()

    def getBlob(self):
        b_y = self._size[1] -(self._size[0] / 96) * (self.blob + 66)
        b_x = self._size[1] - b_y
        return b_x, b_y

    def drawMain(self, qp):
        pass


class GateChart(AudioChart):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cutoff = -36

    def drawMain(self, qp):
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setPen(self.MAIN_LINE)

        co_x = (self._size[0] / 96) * (self.cutoff + 66)
        co_y = self._size[1] -co_x

        qp.drawLine(co_x, co_y, self._size[0], -1)
        qp.drawLine(co_x, co_y + 1, co_x, self._size[1])

    def getBlob(self):
        x, y = super().getBlob()
        if self.blob > self.cutoff or not self.enabled:
            return (x, y)
        else:
            return (x, self._size[1])


class CompChart(AudioChart):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cutoff = -36

    def drawMain(self, qp):
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setPen(self.MAIN_LINE)

        co_x = (self._size[0] / 96) * (self.cutoff + 66)
        co_y = self._size[1] - co_x

        qp.drawLine(co_x + 1, co_y, self._size[0], co_y)
        qp.drawLine(co_x, co_y, -1, self._size[1])

    def getBlob(self):
        x, y = super().getBlob()
        if self.blob < self.cutoff or not self.enabled:
            return (x, y)
        else:
            co_y = self._size[1] - (self._size[0] / 96) * (self.cutoff + 66)

            return (x, co_y)



class ClientPane(QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.rows = VBox(self, Qt.AlignTop)
        self.scroll.setWidget(self.rows)
        self.scroll.setStyleSheet(CLEAR_SCROLL)

        self.setup_sp = VBSpoiler('Client Setup', 100, self.rows)
        self.audio_sp = HBSpoiler('Audio Setup', 100, self.rows)
        self.opus_sp = VBSpoiler('OPUS', 100, self.rows)

        # Client setup
        self.client_name = QLineEdit(self.setup_sp, placeholderText='Display Name')
        self.setup_sp.addWidget(self.client_name)

        # Gate setup
        gate_vb = VBox(self.audio_sp)
        self.gate_enabled = QCheckBox("Gate Enabled", gate_vb)
        self.gate_enabled.setChecked(True)
        self.gate_enabled.clicked.connect(self.gate_enable_change)
        gate_vb.addWidget(self.gate_enabled)

        hb = HBox(gate_vb, Qt.AlignLeft)
        self.gate_chart = GateChart(hb)
        hb.addWidget(self.gate_chart)

        self.gate_slider = QSlider(hb, minimum=-66, maximum=30, singleStep=1, sliderPosition=-36)
        hb.addWidget(self.gate_slider)
        self.gate_slider.valueChanged.connect(self.gate_changed)

        gate_vb.addWidget(hb)
        self.audio_sp.addWidget(gate_vb)

        # Compressor setup
        comp_vb = VBox(self.audio_sp)
        self.comp_enabled = QCheckBox("Compressor Enabled", comp_vb)
        self.comp_enabled.setChecked(True)
        self.comp_enabled.clicked.connect(self.comp_enable_change)
        comp_vb.addWidget(self.comp_enabled)

        hb = HBox(comp_vb, Qt.AlignLeft)
        self.comp_chart = CompChart(hb)
        hb.addWidget(self.comp_chart)

        self.comp_slider = QSlider(hb, minimum=-66, maximum=30, singleStep=1, sliderPosition=-12)
        hb.addWidget(self.comp_slider)
        self.comp_slider.valueChanged.connect(self.comp_changed)

        comp_vb.addWidget(hb)
        self.audio_sp.addWidget(comp_vb)
        # OPUS setup

        # Build spoilers
        self.rows.addWidget(self.setup_sp)
        self.rows.addWidget(self.audio_sp)
        self.rows.addWidget(self.opus_sp)

        # self.setup_sp.open()
        self.audio_sp.open()
        self.layout.addWidget(self.scroll)

        self.gate_enable_change(None, False)
        self.comp_enable_change(None, False)
        self.gate_changed()
        self.comp_changed()

        # Animation
        self.t_client_id = None
        self.u_timer = QTimer()
        self.u_timer.timeout.connect(self.moveBlobs)
        self.u_timer.start(10)

    def moveBlobs(self):
        if not SocketManager.amps:
            return
        amp = SocketManager.amps[list(SocketManager.amps.keys())[0]]
        try:
            amp = thresh_to_db(amp)
        except:
            return

        self.gate_chart.blob = amp
        self.comp_chart.blob = amp
        self.gate_chart.repaint()
        self.comp_chart.repaint()

    def gate_enable_change(self, state, repaint=True):
        if state is None:
            state = self.gate_enabled.isChecked()
        self.gate_chart.enabled = state
        self.gate_slider.setEnabled(state)
        if repaint:
            self.gate_chart.repaint()

    def comp_enable_change(self, state, repaint=True):
        if state is None:
            state = self.comp_enabled.isChecked()
        self.comp_chart.enabled = state
        self.comp_slider.setEnabled(state)
        if repaint:
            self.comp_chart.repaint()

    def gate_changed(self):
        db = self.gate_slider.sliderPosition()
        threshold = db_to_thresh(db)

        threshold = round(threshold)
        for client_id in SocketManager.amps:
            payload = client_id + struct.pack('!4lH', -1, -1, -1, threshold, 6969)
            SocketManager.sock.send_packet(SET_GATE, payload)

        self.gate_chart.cutoff = db
        self.gate_chart.repaint()

    def comp_changed(self):
        db = self.comp_slider.sliderPosition()
        threshold = db_to_thresh(db)

        threshold = round(threshold)
        for client_id in SocketManager.amps:
            payload = client_id + struct.pack('!3lH', -1, -1, threshold, 6969)
            SocketManager.sock.send_packet(SET_COMP, payload)


        self.comp_chart.cutoff = db
        self.comp_chart.repaint()


class Window(QMainWindow):
    def __init__(self, app):
        super().__init__()

        SocketManager.setup()

        self.app = app
        self.setWindowTitle('VoIP Management')

        self.build_menubar()

        self.rooms_pane = RoomsPane(self)
        self.client_pane = ClientPane(self)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.rooms_pane, 'Rooming')
        self.tabs.addTab(self.client_pane, 'Client Setup')
        self.tabs.addTab(QWidget(), 'Server Setup')

        self.resize(1300, 700)

        self.setCentralWidget(self.tabs)

    def quit(self):
        choice = QMessageBox.question(self, 'Quit', 'Are you sure you want to quit?',
                                      QMessageBox.Yes | QMessageBox.No)
        if choice == QMessageBox.Yes:
            self.app.quit()

    def build_menubar(self):
        menu = self.menuBar()

        quit_action = QAction('&Quit', self)
        quit_action.setShortcut('Ctrl+Q')
        quit_action.triggered.connect(self.quit)

        self.statusBar()
        file_ = menu.addMenu('&File')
        file_.addAction(quit_action)


def main():
    application = QApplication(sys.argv)

    win = Window(application)
    win.show()

    sys.exit(application.exec_())
