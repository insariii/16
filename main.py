import json
import socket
import struct
import sys
from queue import Queue

from PyQt6.QtCore import pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


HOST = "127.0.0.1"
PORT = 50505


class NetCom:
    def __init__(self, sock):
        self.sock = sock

    @staticmethod
    def _recv_exact(sock, size):
        chunks = []
        received = 0

        while received < size:
            chunk = sock.recv(size - received)

            if not chunk:
                return None

            chunks.append(chunk)
            received += len(chunk)

        return b"".join(chunks)

    def recv(self):
        header = self._recv_exact(self.sock, 4)

        if header is None:
            return None

        payload_size = struct.unpack("!I", header)[0]
        payload = self._recv_exact(self.sock, payload_size)

        if payload is None:
            return None

        return json.loads(payload.decode("utf-8"))

    def send(self, message):
        payload = json.dumps(
            message, ensure_ascii=False
        ).encode("utf-8")

        header = struct.pack("!I", len(payload))
        self.sock.sendall(header + payload)


class ReceiveThread(QThread):
    message_received = pyqtSignal(dict)
    disconnected = pyqtSignal(str)

    def __init__(self, net):
        super().__init__()
        self.net = net

    def run(self):
        while True:
            try:
                message = self.net.recv()

                if message is None:
                    self.disconnected.emit(
                        "Сервер закрыл соединение."
                    )
                    break

                self.message_received.emit(message)

            except (OSError, ValueError, UnicodeError,
                    struct.error) as error:
                self.disconnected.emit(
                    f"Ошибка получения данных: {error}"
                )
                break


class SendThread(QThread):
    connection_lost = pyqtSignal(str)

    def __init__(self, net):
        super().__init__()
        self.net = net
        self.queue = Queue()

    def send(self, message):
        self.queue.put(message)

    def stop(self):
        self.queue.put(None)

    def run(self):
        while True:
            message = self.queue.get()

            if message is None:
                break

            try:
                self.net.send(message)

            except OSError as error:
                self.connection_lost.emit(
                    f"Ошибка отправки данных: {error}"
                )
                break


class MainWindow(QMainWindow):
    def __init__(self, net):
        super().__init__()

        self.net = net
        self._closing = False
        self._disconnected = False

        self.setWindowTitle("Сетевой чат PyQt6")
        self.resize(560, 460)

        self.username = QLineEdit()
        self.username.setPlaceholderText("Ваше имя")

        self.history = QTextEdit()
        self.history.setReadOnly(True)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Введите сообщение...")

        self.send_button = QPushButton("Отправить")
        self.clear_button = QPushButton("Очистить историю")

        self.status_label = QLabel("Подключено")

        top_row = QHBoxLayout()
        top_row.addWidget(self.status_label)
        top_row.addWidget(QLabel("Ваше имя:"))
        top_row.addWidget(self.username)

        input_row = QHBoxLayout()
        input_row.addWidget(self.input)
        input_row.addWidget(self.send_button)

        layout = QVBoxLayout()
        layout.addLayout(top_row)
        layout.addWidget(self.history)
        layout.addLayout(input_row)
        layout.addWidget(self.clear_button)

        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)

        self.send_button.clicked.connect(
            self.on_send_clicked
        )

        self.input.returnPressed.connect(
            self.on_send_clicked
        )

        self.clear_button.clicked.connect(
            self.history.clear
        )

        self.receive_thread = ReceiveThread(self.net)

        self.receive_thread.message_received.connect(
            self.handle_message
        )

        self.receive_thread.disconnected.connect(
            self.handle_disconnected
        )

        self.send_thread = SendThread(self.net)

        self.send_thread.connection_lost.connect(
            self.handle_disconnected
        )

        self.receive_thread.start()
        self.send_thread.start()

        self.history.append(
            "[Система] Соединение с сервером установлено."
        )

    def on_send_clicked(self):
        if self._disconnected or self._closing:
            return

        text = self.input.text().strip()
        username = self.username.text().strip()

        if not username:
            self.status_label.setText("Введите имя")
            return

        if not text:
            return

        if not self.send_thread.isRunning():
            return

        self.send_thread.send({
            "type": "chat",
            "username": username,
            "text": text
        })

        self.input.clear()

    def handle_message(self, message):
        message_type = message.get("type")

        if message_type == "chat":
            username = message.get(
                "username", "Неизвестный пользователь"
            )
            text = message.get("text", "")

            self.history.append(
                f"{username}: {text}"
            )

        elif message_type == "system":
            text = message.get("text", "")

            self.history.append(
                f"[Система] {text}"
            )

    def handle_disconnected(self, error):
        if self._closing or self._disconnected:
            return

        self._disconnected = True

        self.status_label.setText("Отключено")

        self.history.append(
            f"[Система] Соединение потеряно: {error}"
        )

        self.send_button.setEnabled(False)
        self.input.setEnabled(False)

    def closeEvent(self, event):
        self._closing = True

        self.send_thread.stop()

        try:
            self.net.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        self.receive_thread.wait()
        self.send_thread.wait()

        try:
            self.net.sock.close()
        except OSError:
            pass

        event.accept()


def main():
    app = QApplication(sys.argv)

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    try:
        sock.connect((HOST, PORT))

    except OSError as error:
        print(
            f"Не удалось подключиться к серверу: {error}"
        )
        print(
            "Сначала запустите server.py, затем main.py."
        )
        sock.close()
        return

    net = NetCom(sock)

    window = MainWindow(net)
    window.show()

    exit_code = app.exec()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
