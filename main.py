import random
import socket
import time

from construct import (BitStruct, Bytes, Const, Enum, Flag, Float32b,
                       Int16ul, Int32ul, Int64ul, Int8ul, Struct)
from dataclasses import dataclass, field
from datetime import datetime
from zlib import crc32


SERVER_IP = "127.0.0.1"
SERVER_PORT = 26760
SERVER_ID = random.getrandbits(32)
PROTOCOL_VERSION = 1001
BUFSIZE = 1024

CLIENT_MESSAGE = b"DSUC"
SERVER_MESSAGE = b"DSUS"


TYPE_PROTOCOL_VERSION = 0x100000
TYPE_CONTROLLER_CONNECTED = 0x100001
TYPE_CONTROLLER_DATA = 0x100002
TYPE_SIZE = 4


RH_SLOT_STATE_NOT_CONNECTED = 0
RH_SLOT_STATE_RESERVED = 1
RH_SLOT_STATE_CONNECTED = 2

RH_MODEL_NA = 0
RH_MODEL_PARTIAL_GYRO = 1
RH_MODEL_FULL_GYRO = 2
RH_MODEL_DO_NOT_USE = 3

RH_CONNECTION_NA = 0
RH_CONNECTION_USB = 1
RH_CONNECTION_BLUETOOTH = 2

RH_BATTERY_NA = 0x00
RH_BATTERY_DYING = 0x01
RH_BATTERY_LOW = 0x02
RH_BATTERY_MEDIUM = 0x03
RH_BATTERY_HIGH = 0x04
RH_BATTERY_FULL = 0x05
RH_BATTERY_CHARGING = 0xEE
RH_BATTERY_CHARGED = 0xEF

C_STATE_ACTIVE = 0
C_STATE_INACTIVE = 1


@dataclass
class ClientInfo:
    id: int
    last_seen: datetime
    controllers: dict
    addr: tuple
    sock: socket.socket


@dataclass
class TouchInfo:
    active: int = C_STATE_INACTIVE
    id: int = 0
    x: int = 0
    y: int = 0


@dataclass
class ControllerState:
    connected: int = C_STATE_ACTIVE
    dPadLeft: bool = False
    dPadDown: bool = False
    dPadRight: bool = False
    dPadUp: bool = False
    analogDPadLeft: int = 0
    analogDPadDown: int = 0
    analogDPadRight: int = 0
    analogDPadUp: int = 0
    share: bool = False
    options: bool = False
    home: int = C_STATE_INACTIVE
    touch: int = C_STATE_INACTIVE
    r1: bool = False
    l1: bool = False
    r2: bool = False
    l2: bool = False
    r3: bool = False
    l3: bool = False
    analogR1: int = 0
    analogR2: int = 0
    analogL1: int = 0
    analogL2: int = 0
    a: bool = False
    b: bool = False
    x: bool = False
    y: bool = False
    analogA: int = 0
    analogB: int = 0
    analogX: int = 0
    analogY: int = 0
    firstTouch: TouchInfo = field(default_factory=lambda: TouchInfo())
    secondTouch: TouchInfo = field(default_factory=lambda: TouchInfo())
    leftStickX: int = 0
    leftStickY: int = 0
    rightStickX: int = 0
    rightStickY: int = 0
    accelX: float = 0.0
    accelY: float = 0.0
    accelZ: float = 0.0
    gyroPitch: float = 0.0
    gyroYaw: float = 0.0
    gyroRoll: float = 0.0


@dataclass
class ControllerInfo:
    mac: int
    battery: int
    model: int
    connection_type: int
    slot: int
    slot_state: int
    state: ControllerState = field(default_factory=lambda: ControllerState())


MessageHeader = Struct(
    "source" / Bytes(4),
    "protocol_version" / Const(PROTOCOL_VERSION, Int16ul),
    "packet_length" / Int16ul,
    "crc32" / Int32ul,
    "id" / Int32ul,
    "type" / Enum(
        Int32ul,
        CONNECTED=Const(TYPE_CONTROLLER_CONNECTED, Int32ul),
        DATA=Const(TYPE_CONTROLLER_DATA, Int32ul),
    ),
)

ResponseHeader = Struct(
    "slot" / Int8ul,
    "slot_state" / Int8ul,
    "model" / Int8ul,
    "connection_type" / Int8ul,
    "mac" / Bytes(6),
    "battery" / Int8ul
)

Touch = Struct(
    "active" / Int8ul,
    "id" / Int8ul,
    "x" / Int16ul,
    "y" / Int16ul,
)

ControllerStatePayload = Struct(
    "connected" / Int8ul,
    "packet_number" / Int32ul,
    "buttons1" / BitStruct(
        "dPadLeft" / Flag,
        "dPadDown" / Flag,
        "dPadRight" / Flag,
        "dPadUp" / Flag,
        "options" / Flag,
        "r3" / Flag,
        "l3" / Flag,
        "share" / Flag,
    ),
    "buttons2" / BitStruct(
        "y" / Flag,
        "b" / Flag,
        "a" / Flag,
        "x" / Flag,
        "r1" / Flag,
        "l1" / Flag,
        "r2" / Flag,
        "l2" / Flag,
    ),
    "home" / Int8ul,
    "touch" / Int8ul,
    "leftStickX" / Int8ul,
    "leftStickY" / Int8ul,
    "rightStickX" / Int8ul,
    "rightStickY" / Int8ul,
    "analogDPadLeft" / Int8ul,
    "analogDPadDown" / Int8ul,
    "analogDPadRight" / Int8ul,
    "analogDPadUp" / Int8ul,
    "analogY" / Int8ul,
    "analogB" / Int8ul,
    "analogA" / Int8ul,
    "analogX" / Int8ul,
    "analogR1" / Int8ul,
    "analogL1" / Int8ul,
    "analogR2" / Int8ul,
    "analogL2" / Int8ul,
    "firstTouch" / Touch,
    "secondTouch" / Touch,
    "timestamp" / Int64ul,
    "accelX" / Float32b,
    "accelY" / Float32b,
    "accelZ" / Float32b,
    "gyroPitch" / Float32b,
    "gyroYaw" / Float32b,
    "gyroRoll" / Float32b,
)

ConnectedControllersPayload = Struct(
    "header" / ResponseHeader,
    "data" / Const(0, Int8ul)
)

ControllerStatePayload = Struct(
    "header" / ResponseHeader,
    "data" / ControllerStatePayload
)


SubscribePayload = Struct(
    "type" / Enum(Int8ul, SLOT=1, MAC=2, ALL=0),
    "slot" / Int8ul,
    "mac" / Bytes(6)
)

Message = Struct(
    "header" / MessageHeader,
    "payload" / Bytes(
        lambda ctx: ctx.header.packet_length - TYPE_SIZE
    )
)


clients = {}

controllers = [
    ControllerInfo(
        battery=RH_BATTERY_FULL,
        mac=b'DSU001',
        model=RH_MODEL_FULL_GYRO,
        connection_type=RH_CONNECTION_USB,
        slot_state=RH_SLOT_STATE_CONNECTED,
        slot=0
    ),
    ControllerInfo(
        battery=RH_BATTERY_FULL,
        mac=b'DSU002',
        model=RH_MODEL_FULL_GYRO,
        connection_type=RH_CONNECTION_USB,
        slot_state=RH_SLOT_STATE_CONNECTED,
        slot=0
    )
]


def build_touch_data(touch: TouchInfo):
    return dict(
        active=touch.active,
        id=touch.id,
        x=touch.x,
        y=touch.y
    )


def controller_state_to_info(info: ControllerInfo, packet_number: int):
    s = info.state
    return ControllerStatePayload.build({
        "header": build_controller_header(info),
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
            firstTouch=build_touch_data(s.firstTouch),
            secondTouch=build_touch_data(s.secondTouch),
            accelX=s.accelX,
            accelY=s.accelY,
            accelZ=s.accelZ,
            gyroPitch=s.gyroPitch,
            gyroYaw=s.gyroYaw,
            gyroRoll=s.gyroRoll,
        )
    })


def send_message(to, message_type, payload):
    message = Message.build({
        "header": dict(
            source=SERVER_MESSAGE,
            packet_length=len(payload) + TYPE_SIZE,
            crc32=0,
            id=SERVER_ID,
            type=message_type,
        ),
        "payload": payload
    })
    message = bytearray(message)
    crc = Int32ul.build(crc32(message))
    message[8:12] = crc
    to.sock.sendto(message, to.addr)


def build_controller_header(controller: ControllerInfo):
    return dict(
        slot=controller.slot,
        slot_state=controller.slot_state,
        model=controller.model,
        connection_type=controller.connection_type,
        mac=controller.mac,
        battery=controller.battery
    )


def send_version_info(to: ClientInfo):
    send_message(
        to,
        TYPE_PROTOCOL_VERSION,
        Int16ul.build(PROTOCOL_VERSION)
    )


def send_connected_controllers(to: ClientInfo):
    for controller in controllers:
        payload = ConnectedControllersPayload.build({
            "header": build_controller_header(controller)
        })
        send_message(to, TYPE_CONTROLLER_CONNECTED, payload)


def send_controller_state():
    for controller in controllers:
        for client in clients.values():
            if controller.slot not in client.controllers:
                continue

            client.controllers[controller.slot] += 1
            payload = controller_state_to_info(
                controller,
                client.controllers[controller.slot]
            )
            send_message(client, TYPE_CONTROLLER_DATA, payload)


def subscribe_to_controller(to: ClientInfo, payload: bytes):
    payload = SubscribePayload.parse(payload)
    match payload.type:
        case "SLOT":
            to.controllers.setdefault(payload.slot, 0)
            send_controller_state()

        case _:
            raise NotImplementedError("Only support slot-based subscription")


def main():
    print("Starting server")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((SERVER_IP, SERVER_PORT))
    print(f"DSU server listening on {SERVER_IP}:{SERVER_PORT}...")
    while True:
        data, addr = sock.recvfrom(1024)
        message = Message.parse(data)
        client_id = message.header.id
        clients.setdefault(client_id, ClientInfo(
            id=message.header.id,
            last_seen=datetime.now(),
            addr=addr,
            sock=sock,
            controllers={}
        ))
        client = clients[client_id]
        if message.header.type == TYPE_PROTOCOL_VERSION:
            print(f"Received version request from {addr}")
            send_version_info(client)
        elif message.header.type == TYPE_CONTROLLER_CONNECTED:
            print(f"Received controller request from {addr}")
            send_connected_controllers(client)
        elif message.header.type == TYPE_CONTROLLER_DATA:
            subscribe_to_controller(client, message.payload)
        else:
            raise NotImplementedError(
                f"Unexpected message from {client=}: {data=}, {message=}"
            )


if __name__ == "__main__":
    main()
