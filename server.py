import random
import socket
import time

from contextlib import contextmanager
from datetime import datetime
from threading import Lock, Thread
from zlib import crc32

import datatypes as d


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 26760
BUFSIZE = 1024


class Server:
    def __init__(
            self,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT
    ):
        self.id = random.getrandbits(32)
        self.host = host
        self.port = port
        self.clients = {}
        self._controllers = []
        self.lock = Lock()
        self.thread = None

    @staticmethod
    def build_touch_data(touch: d.TouchInfo):
        return dict(
            active=touch.active,
            id=touch.id,
            x=touch.x,
            y=touch.y
        )

    @contextmanager
    def get_controllers(self):
        with self.lock:
            yield self._controllers

    def append_controller(self, controller: d.ControllerInfo):
        with self.get_controllers() as c:
            c.append(controller)
            return len(c) - 1

    def change_controller(self, slot: int, controller: d.ControllerInfo):
        with self.get_controllers() as c:
            c[slot] = controller

    def controller_state_to_info(
            self,
            info: d.ControllerInfo,
            packet_number: int
    ):
        s = info.state
        return d.ControllerStatePayload.build({
            "header": self.build_controller_header(info),
            "data": dict(
                connected=s.connected,
                packet_number=packet_number,
                buttons1=dict(
                    dPadLeft=s.dPadLeft,
                    dPadDown=s.dPadDown,
                    dPadRight=s.dPadRight,
                    dPadUp=s.dPadUp,
                    options=s.options,
                    share=s.share,
                    r3=s.r3,
                    l3=s.l3,
                ),
                buttons2=dict(
                    a=s.a,
                    b=s.b,
                    x=s.x,
                    y=s.y,
                    l1=s.l1,
                    r1=s.r1,
                    l2=s.l2,
                    r2=s.r2,
                ),
                home=s.home,
                touch=s.touch,
                leftStickX=s.leftStickX,
                leftStickY=s.leftStickY,
                rightStickX=s.rightStickX,
                rightStickY=s.rightStickY,
                analogDPadLeft=s.analogDPadLeft,
                analogDPadDown=s.analogDPadDown,
                analogDPadRight=s.analogDPadRight,
                analogDPadUp=s.analogDPadUp,
                analogA=s.analogA,
                analogB=s.analogB,
                analogX=s.analogX,
                analogY=s.analogY,
                analogL1=s.analogL1,
                analogL2=s.analogL2,
                analogR1=s.analogR1,
                analogR2=s.analogR2,
                timestamp=time.time_ns() // 1000,
                firstTouch=self.build_touch_data(s.firstTouch),
                secondTouch=self.build_touch_data(s.secondTouch),
                accelX=s.accelX,
                accelY=s.accelY,
                accelZ=s.accelZ,
                gyroPitch=s.gyroPitch,
                gyroYaw=s.gyroYaw,
                gyroRoll=s.gyroRoll,
            )
        })

    def send_message(self, to, message_type, payload):
        message = d.Message.build({
            "header": dict(
                source=d.SERVER_MESSAGE,
                packet_length=len(payload) + d.TYPE_SIZE,
                crc32=0,
                id=self.id,
                type=message_type,
            ),
            "payload": payload
        })
        message = bytearray(message)
        crc = d.Int32ul.build(crc32(message))
        message[8:12] = crc
        to.sock.sendto(message, to.addr)

    @staticmethod
    def build_controller_header(controller: d.ControllerInfo):
        return dict(
            slot=controller.slot,
            slot_state=controller.slot_state,
            model=controller.model,
            connection_type=controller.connection_type,
            mac=controller.mac,
            battery=controller.battery
        )

    def send_version_info(self, to: d.ClientInfo):
        self.send_message(
            to,
            d.TYPE_PROTOCOL_VERSION,
            d.Int16ul.build(d.PROTOCOL_VERSION)
        )

    def send_connected_controllers(self, to: d.ClientInfo):
        with self.get_controllers() as controllers:
            for controller in controllers:
                payload = d.ConnectedControllersPayload.build({
                    "header": self.build_controller_header(controller)
                })
                self.send_message(to, d.TYPE_CONTROLLER_CONNECTED, payload)

    def send_controller_state(self):
        with self.get_controllers() as controllers:
            for controller in controllers:
                for client in self.clients.values():
                    if controller.slot not in client.controllers:
                        continue

                    client.controllers[controller.slot] += 1
                    payload = self.controller_state_to_info(
                        controller,
                        client.controllers[controller.slot]
                    )
                    self.send_message(client, d.TYPE_CONTROLLER_DATA, payload)

    def subscribe_to_controller(self, to: d.ClientInfo, payload: bytes):
        payload = d.SubscribePayload.parse(payload)
        match payload.type:
            case "SLOT":
                to.controllers.setdefault(payload.slot, 0)
                self.send_controller_state()
            case _:
                raise NotImplementedError(
                    "Only support slot-based subscription"
                )

    def _do_start(self):
        print("Starting server")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.host, self.port))
        print(f"DSU server listening on {self.host}:{self.port}...")
        while True:
            data, addr = sock.recvfrom(1024)
            message = d.Message.parse(data)
            client_id = message.header.id
            self.clients.setdefault(client_id, d.ClientInfo(
                id=message.header.id,
                last_seen=datetime.now(),
                addr=addr,
                sock=sock,
                controllers={}
            ))
            client = self.clients[client_id]
            if message.header.type == d.TYPE_PROTOCOL_VERSION:
                print(f"Received version request from {addr}")
                self.send_version_info(client)

            elif message.header.type == d.TYPE_CONTROLLER_CONNECTED:
                print(f"Received controller request from {addr}")
                self.send_connected_controllers(client)

            elif message.header.type == d.TYPE_CONTROLLER_DATA:
                self.subscribe_to_controller(client, message.payload)

            else:
                raise NotImplementedError(
                    f"Unexpected message from {client=}: {data=}, {message=}"
                )

    def start_background(self):
        self.thread = Thread(target=self._do_start, daemon=True)
        self.thread.start()
