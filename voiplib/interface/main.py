import struct
import sys
import threading

import math
from PyQt4.QtCore import *
from PyQt4.QtGui import *

from ..audio import AudioIO
from ..audio_processors.base import AudioProcessor
from ..config import *
from ..opcodes import *
from ..socket_controller import SocketController, SocketMode, KeyManager

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


class Communicate(QObject):
    reload_rooms = pyqtSignal()


class SocketManager:
    km = KeyManager()
    sock = SocketController()

    client_sock = SocketController(km=km)
    udp_send = SocketController(SocketMode.UDP, km=km)
    udp_recv = SocketController(SocketMode.UDP, km=km)

    clients = {}
    rooms = []
    client_id = b''

    aio = AudioIO()
    amps = {}

    class AudioReturn(AudioProcessor):
        def __init__(self, amps):
            self.amps = amps

        def process(self, data, packet, amp):
            self.amps[packet.client_id] = amp
            return None

        def clone(self):
            return self.__class__(self.amps)

    signals = Communicate()

    @classmethod
    def mainloop(cls):
        while True:
            pkt = cls.udp_recv.get_packet(True)

            if pkt[2].opcode == AUDIO:
                cls.aio.feed(pkt[2].payload, pkt[2])

    @classmethod
    def tcp_mainloop(cls):
        while True:
            pkt = cls.sock.get_packet(True)

            if pkt[2].opcode == CLIENT_JOIN:
                if pkt[2].payload[:16] == cls.client_id:
                    continue

                n_rooms = pkt[2].payload[30]
                r_data = pkt[2].payload[31:31 + n_rooms]
                payload_rest = pkt[2].payload[31 + n_rooms:]
                name_l = payload_rest[0]
                name = payload_rest[1:1 + name_l].decode('latin-1')

                cls.clients[pkt[2].payload[:16]] = [
                    list(struct.unpack('!4H', pkt[2].payload[16:24])),
                    list(struct.unpack('!3H', pkt[2].payload[24:30])),
                    name
                ]
                for i in r_data:
                    while i >= len(cls.rooms):
                        cls.rooms.append([])
                    cls.rooms[i].append(pkt[2].payload[:16])

                cls.signals.reload_rooms.emit()

    @classmethod
    def setup(cls):
        cls.sock.connect(SERVER, CONTROL_PORT)
        cls.sock.start()
        cls.sock.use_special_encryption = True
        cls.sock.do_tcp_client_auth()

        cls.client_sock.connect(SERVER, TCP_PORT)
        cls.client_sock.use_special_encryption = True
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
        cls.sock.send_packet(REGISTER_UDP, reg_udp)

        cls.aio.back_pipeline.append(cls.AudioReturn(cls.amps))
        cls.aio.begin()

        threading.Thread(target=cls.mainloop, daemon=True).start()
        threading.Thread(target=cls.tcp_mainloop, daemon=True).start()


class HBox(QWidget):
    def __init__(self, parent, align=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self.setLayout(self._layout)

        if align:
            self._layout.setAlignment(align)

    def count(self):
        return self._layout.count()

    def itemAt(self, x):
        return self._layout.itemAt(x)

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
    def __init__(self, title, animation_duration, parent):
        super().__init__(parent)
        self.animationDuration = animation_duration

        self.toggleButton = QToolButton()
        self.toggleButton.setStyleSheet("QToolButton { border: none; }")
        self.toggleButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggleButton.setArrowType(Qt.RightArrow)
        self.toggleButton.setText(title)
        self.toggleButton.setCheckable(False)
        self.toggleButton.setChecked(False)

        self._open = False

        header_line = QFrame()
        header_line.setFrameShape(QFrame.HLine)
        header_line.setFrameShadow(QFrame.Sunken)
        header_line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

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
        main_layout = QGridLayout()
        main_layout.setVerticalSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        row = 0
        main_layout.addWidget(self.toggleButton, row, 0, 1, 1, Qt.AlignLeft)
        main_layout.addWidget(header_line, row, 2, 1, 1)
        row += 1
        main_layout.addWidget(self.contentArea, row, 0, 1, 3)

        self.setLayout(main_layout)
        self.setLayout(main_layout)
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

    def set_content_layout(self, content_layout):
        self.contentArea.setLayout(content_layout)
        self.reload_content_layout()

    def reload_content_layout(self):
        collapsed_height = self.sizeHint().height() - self.contentArea.maximumHeight()
        content_height = self.contentArea.layout().sizeHint().height()

        for i in range(self.toggleAnimation.animationCount() - 1):
            spoiler_anim = self.toggleAnimation.animationAt(i)
            spoiler_anim.setDuration(self.animationDuration)
            spoiler_anim.setStartValue(collapsed_height)
            spoiler_anim.setEndValue(collapsed_height + content_height)

        content_anim = self.toggleAnimation.animationAt(self.toggleAnimation.animationCount() - 1)
        content_anim.setDuration(self.animationDuration)
        content_anim.setStartValue(0)
        content_anim.setEndValue(content_height)


class VBSpoiler(Spoiler):
    def __init__(self, *args):
        super().__init__(*args)

        self._layout = QVBoxLayout()

        self.set_content_layout(self._layout)

    def addWidget(self, widget):
        self._layout.addWidget(widget)
        self.reload_content_layout()


class HBSpoiler(Spoiler):
    def __init__(self, *args):
        super().__init__(*args)

        self._layout = QHBoxLayout()

        self.set_content_layout(self._layout)

    def addWidget(self, widget):
        self._layout.addWidget(widget)
        self.reload_content_layout()


class MetadataListModel(QAbstractListModel):
    MetadataRole = Qt.UserRole

    MaxRole = MetadataRole

    def __init__(self, source=False):
        super().__init__()
        self.listdata = []
        self.tooltips = []
        self.metadata = []
        self.data_changed = None

        self.source = source

        self.setSupportedDragActions(Qt.CopyAction if self.source else Qt.MoveAction)
        self.sort(0)

    # Custom methods
    def add_item(self, text, tooltip=None, metadata=None):
        self.listdata.append(text)
        self.tooltips.append(tooltip)
        self.metadata.append(metadata)
        self.sort(0)

        self.dataChanged.emit(self.index(0, 0), self.index(0, len(self.listdata)))

    def clear(self):
        original = len(self.listdata)
        self.listdata.clear()
        self.tooltips.clear()
        self.metadata.clear()

        self.dataChanged.emit(self.index(0, 0), self.index(0, original))

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
        self.beginRemoveRows(parent, row, row + count - 1)
        self.listdata = self.listdata[:row] + self.listdata[row + count:]
        self.tooltips = self.tooltips[:row] + self.tooltips[row + count:]
        self.metadata = self.metadata[:row] + self.metadata[row + count:]
        self.endRemoveRows()

        if self.data_changed is not None:
            self.data_changed()

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

        if self.data_changed is not None:
            self.data_changed()

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
        self.beginInsertRows(parent, row, row + count - 1)

        row = max(row, 0)
        self.listdata = self.listdata[:row] + [None] * count + self.listdata[row:]
        self.tooltips = self.tooltips[:row] + [None] * count + self.tooltips[row:]
        self.metadata = self.metadata[:row] + [None] * count + self.metadata[row:]
        self.endInsertRows()

        if self.data_changed is not None:
            self.data_changed()

        return True

    def itemData(self, index):
        roles = {}
        for i in range(self.MaxRole + 1):
            variant_data = self.data(index, i)
            if variant_data is not None:
                roles[i] = variant_data
        return roles


class RoomsPane(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self._parent = parent

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(CLEAR_SCROLL)

        self.columns = HBox(self)
        self.scroll.setWidget(self.columns)

        self.cols = []
        self.models = []
        self.add_column('All Clients', 0)

        self.layout.addWidget(self.scroll)

        self.reload_rooms()
        SocketManager.signals.reload_rooms.connect(self.reload_rooms)

    def data_changed(self):
        while len(SocketManager.rooms) < len(self.models) - 1:
            SocketManager.rooms.append([])

        for n, i in enumerate(SocketManager.rooms):
            i.clear()
            for j in self.models[n + 1].metadata:
                if j:
                    i.append(j['client_id'])

        for client_id in SocketManager.clients:
            rooms = bytearray([n for n, i in enumerate(SocketManager.rooms) if client_id in i])
            rooms.insert(0, len(rooms))

            payload = client_id + rooms
            SocketManager.sock.send_packet(SET_ROOMS, payload)

    def reload_rooms(self):
        while len(SocketManager.rooms) + 1 >= len(self.cols):
            self.add_column(f'Room #{len(self.cols)}', len(self.cols))

        for model in self.models:
            model.clear()

        for n, c in enumerate(SocketManager.clients):
            name = SocketManager.clients[c][2] or 'NO NAME'
            ip = f'192.168.0.{n + 1}'
            mac = '00:11:22:33:44:55:66'

            for m, i in enumerate(self.models):
                if m == 0 or (m <= len(SocketManager.rooms) and c in SocketManager.rooms[m - 1]):
                    self.models[m].add_item(name, f'Name: {name}\nIP: {ip}\nMAC: {mac}', metadata={
                        'client_id': c
                    })

    def add_column(self, name, n, width=250):
        while n >= len(self.cols):
            self.cols.append(None)
            self.models.append(None)

        self.cols[n] = VBox(self.columns)
        self.cols[n].setContentsMargins(0, 0, 0, 0)
        heading = QLabel(name, self.cols[n])
        heading.setFixedWidth(width)
        self.cols[n].addWidget(heading)

        view = QListView()
        self.models[n] = MetadataListModel(n == 0)
        self.models[n].data_changed = self.data_changed
        view.setModel(self.models[n])
        view.setDragDropMode(QAbstractItemView.DragDrop)
        view.setDefaultDropAction(Qt.MoveAction)

        view.doubleClicked.connect(self.open_client(self.models[n]))
        self.cols[n].addWidget(view)

        self.columns.addWidget(self.cols[n])

    def open_client(self, model):
        def _open_client(index):
            data = model.data(index, model.MetadataRole)

            cw = self._parent.client_window

            cw.gate_chart.cutoff = thresh_to_db(SocketManager.clients[data['client_id']][0][3])
            cw.gate_slider.setValue(thresh_to_db(SocketManager.clients[data['client_id']][0][3]))
            cw.comp_chart.cutoff = thresh_to_db(SocketManager.clients[data['client_id']][1][2])
            cw.comp_slider.setValue(thresh_to_db(SocketManager.clients[data['client_id']][1][2]))

            cw.client_name.setText(SocketManager.clients[data['client_id']][2])

            cw.gate_chart.repaint()
            cw.comp_chart.repaint()

            cw.target_client_id = data['client_id']
            cw.show()

        return _open_client


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
        b_y = self._size[1] - (self._size[0] / 96) * (self.blob + 66)
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
        co_y = self._size[1] - co_x

        qp.drawLine(co_x, co_y, self._size[0], -1)
        qp.drawLine(co_x, co_y + 1, co_x, self._size[1])

    def getBlob(self):
        x, y = super().getBlob()
        if self.blob > self.cutoff or not self.enabled:
            return x, y
        else:
            return x, self._size[1]


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
            return x, y
        else:
            co_y = self._size[1] - (self._size[0] / 96) * (self.cutoff + 66)

            return x, co_y


class ClientWindow(QMainWindow):
    def __init__(self, parent):
        super().__init__(parent)
        self.target_client_id = None

        self.layout = VBox(self)
        self.setCentralWidget(self.layout)
        self.setWindowTitle('Client Management')
        self.resize(1200, 600)

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
        self.client_name.textChanged.connect(self.name_changed)

        # Gate setup
        gate_vb = VBox(self.audio_sp)
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

        self.setup_sp.open()
        self.audio_sp.open()
        self.layout.addWidget(self.scroll)

        # Animation
        self.t_client_id = None
        self.u_timer = QTimer()
        self.u_timer.timeout.connect(self.move_blobs)
        self.u_timer.start(10)

    def name_changed(self, new_name):
        if self.target_client_id is None:
            return
        payload = self.target_client_id + new_name.encode('latin-1')
        SocketManager.sock.send_packet(SET_NAME, payload)
        SocketManager.clients[self.target_client_id][2] = new_name

        SocketManager.signals.reload_rooms.emit()

    def move_blobs(self):
        if not SocketManager.amps:
            return
        if self.target_client_id is None:
            return
        amp = SocketManager.amps.get(self.target_client_id, 0)

        try:
            amp = thresh_to_db(amp)
        except (ValueError, ZeroDivisionError):
            return

        self.gate_chart.blob = amp
        self.comp_chart.blob = amp
        self.gate_chart.repaint()
        self.comp_chart.repaint()

    def gate_changed(self):
        if self.target_client_id is None:
            return
        db = self.gate_slider.sliderPosition()
        threshold = db_to_thresh(db)
        SocketManager.clients[self.target_client_id][0][3] = threshold

        threshold = round(threshold)
        payload = self.target_client_id + struct.pack('!4lH', -1, -1, -1, threshold, 6969)
        SocketManager.sock.send_packet(SET_GATE, payload)

        self.gate_chart.cutoff = db
        self.gate_chart.repaint()

    def comp_changed(self):
        if self.target_client_id is None:
            return
        db = self.comp_slider.sliderPosition()
        threshold = db_to_thresh(db)
        SocketManager.clients[self.target_client_id][1][2] = threshold

        threshold = round(threshold)
        payload = self.target_client_id + struct.pack('!3lH', -1, -1, threshold, 6969)
        SocketManager.sock.send_packet(SET_COMP, payload)

        self.comp_chart.cutoff = db
        self.comp_chart.repaint()

    def closeEvent(self, event):
        self.target_client_id = None


class Window(QMainWindow):
    def __init__(self, app):
        super().__init__()

        SocketManager.setup()

        self.app = app
        self.setWindowTitle('VoIP Management')

        self.build_menubar()

        self.rooms_pane = RoomsPane(self)
        self.client_window = ClientWindow(self)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.rooms_pane, 'Rooming')
        # self.tabs.addTab(self.client_pane, 'Client Setup')
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
