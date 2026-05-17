import ctypes
import json
import math
import os
import platform
import sdl3

import datatypes as d
from server import Server

os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"


RAD2DEG = 180 / math.pi
MS2_TO_G = 1.0 / 9.80665

REFRESH_DELAY = 10

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 900
LEFT_PANEL = 300
TEXT_BLOCK = 20
PANEL_OFFSET = 15

BG = (18, 18, 22, 255)
PANEL = (35, 35, 42, 255)

WHITE = (240, 240, 240, 255)
GRAY = (120, 120, 120, 255)
DARK_GRAY = (50, 50, 50, 255)


GREEN = (40, 220, 120, 255)
RED = (220, 60, 60, 255)
BLUE = (90, 150, 255, 255)
YELLOW = (255, 210, 60, 255)
ORANGE = (255, 140, 40, 255)
CYAN = (50, 220, 255, 255)


def get_default_font():
    system = platform.system()

    if system == "Windows":
        return b"C:\\Windows\\Fonts\\arial.ttf"

    if system == "Darwin":
        return b"/System/Library/Fonts/Supplemental/Arial.ttf"

    return b"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


FONT_PATH = get_default_font()


def normalize_axis(v):
    return v / 32767.0


def normalize_axis_int(v):
    return max(
        0,
        min(
            255,
            int((v + 0.5) * 255)
        )
    )


def normalize_trigger(v):
    return (v + 32768) / 65535.0


def normalize_trigger_int(v):
    return max(
        0,
        min(
            255,
            int(v * 255)
        )
    )


class Gamepad:
    def __init__(self, jid, server: Server):
        self.jid = jid
        self.pad = sdl3.SDL_OpenGamepad(jid)
        self.name = sdl3.SDL_GetGamepadName(self.pad).decode()
        self.vendor = sdl3.SDL_GetGamepadVendor(self.pad)
        self.product = sdl3.SDL_GetGamepadProduct(self.pad)
        serial = sdl3.SDL_GetGamepadSerial(self.pad)
        self.info = d.ControllerInfo(
            mac=f"dsu{jid:03}".encode(),
            slot_state=d.RH_SLOT_STATE_CONNECTED,
        )

        self.serial = (serial.decode() if serial else "N/A")
        has_gyro = False
        has_accel = False

        if sdl3.SDL_GamepadHasSensor(self.pad, sdl3.SDL_SENSOR_GYRO):
            sdl3.SDL_SetGamepadSensorEnabled(
                self.pad, sdl3.SDL_SENSOR_GYRO, True
            )
            has_gyro = True

        if sdl3.SDL_GamepadHasSensor(self.pad, sdl3.SDL_SENSOR_ACCEL):
            sdl3.SDL_SetGamepadSensorEnabled(
                self.pad, sdl3.SDL_SENSOR_ACCEL, True
            )
            has_accel = True

        if has_gyro and has_accel:
            self.info.model = d.RH_MODEL_FULL_GYRO
        elif has_gyro or has_accel:
            self.info.model = d.RH_MODEL_PARTIAL_GYRO

        self.server = server
        slot = self.server.append_controller(self.info)
        self.info.slot = slot

    def set_state(self, state: d.ControllerState):
        self.info.state = state
        self.server.change_controller(self.info.slot, self.info)

    def close(self):
        if self.pad:
            sdl3.SDL_CloseGamepad(self.pad)
            self.pad = None


class App:
    CALIB_FILE = "gamepad_calibration.json"

    def __init__(self, server: Server):
        if not sdl3.SDL_Init(
            sdl3.SDL_INIT_VIDEO |
            sdl3.SDL_INIT_GAMEPAD |
            sdl3.SDL_INIT_SENSOR
        ):
            raise RuntimeError(sdl3.SDL_GetError().decode())

        if not sdl3.TTF_Init():
            raise RuntimeError("SDL_ttf initialization failed")

        self.window = sdl3.SDL_CreateWindow(
            b"SDL3 DSU Server",
            WINDOW_WIDTH,
            WINDOW_HEIGHT,
            0
        )

        self.renderer = sdl3.SDL_CreateRenderer(self.window, None)

        self.font = sdl3.TTF_OpenFont(FONT_PATH, 15)
        if not self.font:
            raise RuntimeError(f"Could not open font: {FONT_PATH.decode()}")

        self.running = True

        self.gamepads = []
        self.selected = 0
        self.calibration = {}
        self.load_calibration()
        self.calibrating = False
        self.calib_stage = 0
        self.calib_samples = []

        self.server = server
        self.refresh_gamepads()

    def load_calibration(self):
        if not os.path.exists(self.CALIB_FILE):
            self.calibration = {}
            return

        with open(self.CALIB_FILE, "r", encoding="utf-8") as f:
            self.calibration = json.load(f)

    def save_calibration(self):
        with open(self.CALIB_FILE, "w", encoding="utf-8") as f:
            json.dump(self.calibration, f, indent=2)

    def get_pad_key(self, gpinfo):
        return f"{gpinfo.vendor}-{gpinfo.product}-{gpinfo.serial}"

    def ensure_calib(self, key):
        if key not in self.calibration:
            self.calibration[key] = {
                "sticks": {
                    "lx": 0, "ly": 0,
                    "rx": 0, "ry": 0
                },
                "gyro_bias": [0.0, 0.0, 0.0],
                "accel_bias": [0.0, 0.0, 0.0]
            }

    def refresh_gamepads(self):
        for g in self.gamepads:
            g.close()

        self.gamepads = []

        count = ctypes.c_int()
        ids = sdl3.SDL_GetGamepads(ctypes.byref(count))

        if ids:
            for i in range(count.value):
                jid = ids[i]
                if sdl3.SDL_IsGamepad(jid):
                    try:
                        self.gamepads.append(Gamepad(jid, self.server))
                    except Exception as e:
                        print(e)

            sdl3.SDL_free(ids)

    def draw_rect(self, x, y, w, h, color):
        sdl3.SDL_SetRenderDrawColor(self.renderer, *color)
        rect = sdl3.SDL_FRect(float(x), float(y), float(w), float(h))
        sdl3.SDL_RenderFillRect(self.renderer, rect)

    def draw_circle(self, cx, cy, r, color):
        sdl3.SDL_SetRenderDrawColor(self.renderer, *color)
        for angle in range(360):
            rad = math.radians(angle)
            x = cx + math.cos(rad) * r
            y = cy + math.sin(rad) * r
            sdl3.SDL_RenderPoint(self.renderer, x, y)

    def fill_circle(self, cx, cy, r, color):
        sdl3.SDL_SetRenderDrawColor(self.renderer, *color)
        for y in range(-r, r):
            for x in range(-r, r):
                if x * x + y * y <= r * r:
                    sdl3.SDL_RenderPoint(self.renderer, cx + x, cy + y)

    def draw_text(self, text, x, y, color=WHITE):
        surface = sdl3.TTF_RenderText_Blended(
            self.font,
            text.encode(),
            len(text),
            sdl3.SDL_Color(*color),
        )

        if not surface:
            return

        texture = sdl3.SDL_CreateTextureFromSurface(
            self.renderer, surface
        )

        rect = sdl3.SDL_FRect(
            float(x),
            float(y),
            float(surface.contents.w),
            float(surface.contents.h)
        )

        sdl3.SDL_RenderTexture(
            self.renderer,
            texture,
            None,
            rect
        )

        sdl3.SDL_DestroyTexture(texture)
        sdl3.SDL_DestroySurface(surface)

    def draw_sensor_values(
        self,
        title,
        values,
        x,
        y
    ):
        self.draw_text(title, x, y, YELLOW)

        labels = ["X", "Y", "Z"]
        colors = [RED, GREEN, BLUE]

        for i in range(3):
            val = values[i]
            self.draw_text(
                f"{labels[i]}: {val:.3f}",
                x,
                y + 40 + i * 35,
                colors[i]
            )

            width = int(val * 50)

            self.draw_rect(
                x + 120,
                y + 48 + i * 35,
                width,
                16,
                colors[i]
            )

    def draw_gamepad(self, gpinfo: Gamepad):
        s = d.ControllerState()
        gp = gpinfo.pad

        center_x = 760
        center_y = 420

        # =========================================================
        # INFO
        # =========================================================

        self.draw_text(
            gpinfo.name, LEFT_PANEL + PANEL_OFFSET, PANEL_OFFSET, YELLOW
        )
        self.draw_text(
            f"Vendor: {gpinfo.vendor}",
            LEFT_PANEL + PANEL_OFFSET,
            PANEL_OFFSET + TEXT_BLOCK
        )
        self.draw_text(
            f"Product: {gpinfo.product}",
            LEFT_PANEL + PANEL_OFFSET,
            PANEL_OFFSET + TEXT_BLOCK * 2
        )
        self.draw_text(
            f"Serial: {gpinfo.serial}",
            LEFT_PANEL + PANEL_OFFSET,
            PANEL_OFFSET + TEXT_BLOCK * 3
        )

        # =========================================================
        # BATTERY
        # =========================================================

        battery_percent = ctypes.c_int()
        sdl3.SDL_GetGamepadPowerInfo(gp, ctypes.byref(battery_percent))
        battery = battery_percent.value
        self.draw_text(
            f"Battery: {battery}%",
            LEFT_PANEL + PANEL_OFFSET,
            PANEL_OFFSET + TEXT_BLOCK * 4
        )

        self.draw_rect(
            330,
            185,
            220,
            32,
            DARK_GRAY
        )

        battery_color = GREEN

        if battery < 25:
            battery_color = RED
        elif battery < 50:
            battery_color = ORANGE

        self.draw_rect(
            334,
            189,
            int((battery / 100.0) * 212),
            24,
            battery_color
        )

        # =========================================================
        # AXES
        # =========================================================

        lx = normalize_axis(
            sdl3.SDL_GetGamepadAxis(
                gp, sdl3.SDL_GAMEPAD_AXIS_LEFTX
            )
        )

        ly = normalize_axis(
            sdl3.SDL_GetGamepadAxis(
                gp, sdl3.SDL_GAMEPAD_AXIS_LEFTY
            )
        )

        rx = normalize_axis(
            sdl3.SDL_GetGamepadAxis(
                gp, sdl3.SDL_GAMEPAD_AXIS_RIGHTX
            )
        )

        ry = normalize_axis(
            sdl3.SDL_GetGamepadAxis(
                gp, sdl3.SDL_GAMEPAD_AXIS_RIGHTY
            )
        )

        lt = normalize_trigger(
            sdl3.SDL_GetGamepadAxis(
                gp, sdl3.SDL_GAMEPAD_AXIS_LEFT_TRIGGER
            )
        )
        s.analogL2 = normalize_trigger_int(lt)

        rt = normalize_trigger(
            sdl3.SDL_GetGamepadAxis(
                gp, sdl3.SDL_GAMEPAD_AXIS_RIGHT_TRIGGER
            )
        )
        s.analogR2 = normalize_trigger_int(rt)

        # =========================================================
        # STICKS
        # =========================================================

        left_stick_x = center_x - 250
        left_stick_y = center_y + 140

        right_stick_x = center_x + 250
        right_stick_y = center_y + 140

        # Left stick

        self.draw_circle(
            left_stick_x,
            left_stick_y,
            72,
            WHITE
        )

        self.fill_circle(
            left_stick_x + lx * 48,
            left_stick_y + ly * 48,
            14,
            CYAN
        )

        # Right stick

        self.draw_circle(
            right_stick_x,
            right_stick_y,
            72,
            WHITE
        )

        self.fill_circle(
            right_stick_x + rx * 48,
            right_stick_y + ry * 48,
            14,
            CYAN
        )

        self.draw_text(
            f"LX {lx:.2f}",
            left_stick_x - 40,
            left_stick_y + 95
        )

        self.draw_text(
            f"LY {ly:.2f}",
            left_stick_x - 40,
            left_stick_y + 125
        )

        self.draw_text(
            f"RX {rx:.2f}",
            right_stick_x - 40,
            right_stick_y + 95
        )

        self.draw_text(
            f"RY {ry:.2f}",
            right_stick_x - 40,
            right_stick_y + 125
        )

        # =========================================================
        # L3 / R3
        # =========================================================

        l3 = sdl3.SDL_GetGamepadButton(
            gp, sdl3.SDL_GAMEPAD_BUTTON_LEFT_STICK
        )
        s.l3 = l3

        r3 = sdl3.SDL_GetGamepadButton(
            gp, sdl3.SDL_GAMEPAD_BUTTON_RIGHT_STICK
        )
        s.r3 = r3

        self.draw_rect(
            left_stick_x - 32,
            left_stick_y - 120,
            64,
            26,
            GREEN if l3 else GRAY
        )

        self.draw_rect(
            right_stick_x - 32,
            right_stick_y - 120,
            64,
            26,
            GREEN if r3 else GRAY
        )

        self.draw_text(
            "L3",
            left_stick_x - 12,
            left_stick_y - 116
        )

        self.draw_text(
            "R3",
            right_stick_x - 12,
            right_stick_y - 116
        )

        # =========================================================
        # TRIGGERS
        # =========================================================

        def trigger_bar(x, y, value, label):

            self.draw_text(
                label,
                x,
                y - 28
            )

            self.draw_rect(
                x,
                y,
                42,
                200,
                DARK_GRAY
            )

            self.draw_rect(
                x + 5,
                y + 200 - int(value * 190),
                32,
                int(value * 190),
                GREEN
            )

            self.draw_text(
                f"{value:.2f}",
                x - 5,
                y + 215
            )

        trigger_bar(
            center_x - 360,
            250,
            lt,
            "LT"
        )

        trigger_bar(
            center_x + 320,
            250,
            rt,
            "RT"
        )

        # =========================================================
        # SHOULDERS
        # =========================================================

        lb = sdl3.SDL_GetGamepadButton(
            gp, sdl3.SDL_GAMEPAD_BUTTON_LEFT_SHOULDER
        )
        s.l1 = lb

        rb = sdl3.SDL_GetGamepadButton(
            gp, sdl3.SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER
        )
        s.r1 = rb

        self.draw_rect(
            center_x - 330,
            210,
            120,
            32,
            GREEN if lb else GRAY
        )

        self.draw_rect(
            center_x + 210,
            210,
            120,
            32,
            GREEN if rb else GRAY
        )

        self.draw_text(
            "LB",
            center_x - 285,
            216
        )

        self.draw_text(
            "RB",
            center_x + 255,
            216
        )

        # =========================================================
        # DPAD
        # =========================================================

        dpad_up = sdl3.SDL_GetGamepadButton(
            gp, sdl3.SDL_GAMEPAD_BUTTON_DPAD_UP
        )
        s.dPadUp = dpad_up

        dpad_down = sdl3.SDL_GetGamepadButton(
            gp, sdl3.SDL_GAMEPAD_BUTTON_DPAD_DOWN
        )
        s.dPadDown = dpad_down

        dpad_left = sdl3.SDL_GetGamepadButton(
            gp, sdl3.SDL_GAMEPAD_BUTTON_DPAD_LEFT
        )
        s.dPadLeft = dpad_left

        dpad_right = sdl3.SDL_GetGamepadButton(
            gp, sdl3.SDL_GAMEPAD_BUTTON_DPAD_RIGHT
        )
        s.dPadRight = dpad_right

        dx = center_x - 260
        dy = center_y - 30

        size = 38

        self.draw_rect(
            dx,
            dy - size,
            size,
            size,
            GREEN if dpad_up else GRAY
        )

        self.draw_rect(
            dx,
            dy + size,
            size,
            size,
            GREEN if dpad_down else GRAY
        )

        self.draw_rect(
            dx - size,
            dy,
            size,
            size,
            GREEN if dpad_left else GRAY
        )

        self.draw_rect(
            dx + size,
            dy,
            size,
            size,
            GREEN if dpad_right else GRAY
        )

        self.draw_rect(
            dx,
            dy,
            size,
            size,
            WHITE
        )

        # =========================================================
        # FACE BUTTONS
        # =========================================================

        face_buttons = [
            ("Y", sdl3.SDL_GAMEPAD_BUTTON_NORTH, center_x + 260, center_y - 70),
            ("A", sdl3.SDL_GAMEPAD_BUTTON_SOUTH, center_x + 260, center_y + 10),
            ("X", sdl3.SDL_GAMEPAD_BUTTON_WEST, center_x + 220, center_y - 30),
            ("B", sdl3.SDL_GAMEPAD_BUTTON_EAST, center_x + 300, center_y - 30),
        ]

        for label, btn, x, y in face_buttons:
            pressed = sdl3.SDL_GetGamepadButton(
                gp, btn
            )
            setattr(s, label.lower(), pressed)

            self.fill_circle(
                x,
                y,
                24,
                GREEN if pressed else GRAY
            )

            self.draw_circle(
                x,
                y,
                24,
                WHITE
            )

            self.draw_text(
                label,
                x - 6,
                y - 10
            )

        # =========================================================
        # CENTER BUTTONS
        # =========================================================

        center_buttons = [
            (
                "BACK",
                "options",
                sdl3.SDL_GAMEPAD_BUTTON_BACK,
                center_x - 80,
                center_y - 110
            ),
            (
                "HOME",
                "touch",
                sdl3.SDL_GAMEPAD_BUTTON_GUIDE,
                center_x,
                center_y - 85
            ),
            (
                "START",
                "share",
                sdl3.SDL_GAMEPAD_BUTTON_START,
                center_x + 80,
                center_y - 110
            ),
        ]

        for label, attr, btn, x, y in center_buttons:
            pressed = sdl3.SDL_GetGamepadButton(gp, btn)
            setattr(s, attr, pressed)

            self.draw_rect(
                x - 35,
                y - 14,
                70,
                28,
                GREEN if pressed else GRAY
            )

            self.draw_text(
                label,
                x - 24,
                y - 8
            )

        # =========================================================
        # GYROSCOPE
        # =========================================================

        gyro = [0.0, 0.0, 0.0]

        if sdl3.SDL_GamepadHasSensor(
            gp,
            sdl3.SDL_SENSOR_GYRO
        ):

            data = (ctypes.c_float * 3)()

            if sdl3.SDL_GetGamepadSensorData(
                gp,
                sdl3.SDL_SENSOR_GYRO,
                data,
                3
            ):
                gyro = [
                    data[0],
                    data[1],
                    data[2]
                ]

        # =========================================================
        # ACCELEROMETER
        # =========================================================

        accel = [0.0, 0.0, 0.0]

        if sdl3.SDL_GamepadHasSensor(
            gp,
            sdl3.SDL_SENSOR_ACCEL
        ):

            data = (ctypes.c_float * 3)()

            if sdl3.SDL_GetGamepadSensorData(
                gp,
                sdl3.SDL_SENSOR_ACCEL,
                data,
                3
            ):
                accel = [
                    data[0],
                    data[1],
                    data[2]
                ]

        # =========================================================
        # CALIBRATION
        # =========================================================

        self.draw_rect(
            330,
            220,
            200,
            40,
            GREEN if self.calibrating else GRAY
        )

        self.draw_text(
            "CALIBRATE",
            360,
            230
        )
        key = self.get_pad_key(gpinfo)
        self.ensure_calib(key)

        if self.calibrating and len(self.calib_samples) < 60:

            self.calib_samples.append({
                "lx": lx,
                "ly": ly,
                "rx": rx,
                "ry": ry,
                "gx": gyro[0],
                "gy": gyro[1],
                "gz": gyro[2],
                "ax": accel[0],
                "ay": accel[1],
                "az": accel[2]
            })

            self.draw_text(
                "CALIBRATING... KEEP CONTROLLER STILL",
                330,
                270,
                RED
            )

        elif self.calibrating and len(self.calib_samples) >= 60:

            def avg(k): return sum(
                s[k] for s in self.calib_samples) / len(self.calib_samples)

            self.calibration[key]["sticks"] = {
                "lx": avg("lx"),
                "ly": avg("ly"),
                "rx": avg("rx"),
                "ry": avg("ry"),
            }

            self.calibration[key]["gyro_bias"] = [
                avg("gx"),
                avg("gy"),
                avg("gz"),
            ]

            self.calibration[key]["accel_bias"] = [
                avg("ax"),
                avg("ay"),
                avg("az"),
            ]

            self.save_calibration()

            self.calibrating = False
            self.calib_samples = []

        calib = self.apply_calibration(
            key,
            lx, ly,
            rx, ry,
            gyro[0], gyro[1], gyro[2],
            accel[0], accel[1], accel[2]
        )

        lx, ly, rx, ry, gx, gy, gz, ax, ay, az = calib
        s.leftStickX = normalize_axis_int(lx)
        s.leftStickY = normalize_axis_int(ly)
        s.rightStickX = normalize_axis_int(rx)
        s.rightStickY = normalize_axis_int(ry)
        s.accelX = -ax * MS2_TO_G
        s.accelY = -ay * MS2_TO_G
        s.accelZ = az * MS2_TO_G
        s.gyroPitch = gx * RAD2DEG
        s.gyroYaw = -gy * RAD2DEG
        s.gyroRoll = gz * RAD2DEG

        self.draw_sensor_values("GYROSCOPE", [gx, gy, gz],  330, 700)
        self.draw_sensor_values("ACCELEROMETER", [ax, ay, az], 760, 700)
        gpinfo.set_state(s)

    def render(self):

        sdl3.SDL_SetRenderDrawColor(
            self.renderer,
            *BG
        )

        sdl3.SDL_RenderClear(
            self.renderer
        )

        self.draw_rect(
            0,
            0,
            LEFT_PANEL,
            WINDOW_HEIGHT,
            PANEL
        )

        for i, gp in enumerate(self.gamepads):

            y = i * 60

            selected = (
                i == self.selected
            )

            self.draw_rect(
                0,
                y,
                LEFT_PANEL,
                58,
                BLUE if selected else PANEL
            )

            self.draw_text(
                gp.name,
                20,
                y + 18
            )

        if self.gamepads:

            self.draw_gamepad(
                self.gamepads[self.selected]
            )

        else:

            self.draw_text(
                "No gamepads connected",
                350,
                200,
                RED
            )

        sdl3.SDL_RenderPresent(
            self.renderer
        )

    def handle_calibration_click(self, x, y, gpinfo):
        if 330 <= x <= 530 and 220 <= y <= 260:
            self.start_calibration(gpinfo)

    def mouse_click(self, x, y):
        if x < LEFT_PANEL:
            idx = y // 60
            if 0 <= idx < len(self.gamepads):
                self.selected = int(idx)

        if self.gamepads:
            self.handle_calibration_click(
                x,
                y,
                self.gamepads[self.selected]
            )

    def start_calibration(self, gpinfo):
        self.calibrating = True
        self.calib_stage = 0
        self.calib_samples = []
        self.current_calib_key = self.get_pad_key(gpinfo)

    def apply_calibration(self, key, lx, ly, rx, ry, gx, gy, gz, ax, ay, az):
        c = self.calibration.get(key)
        if not c:
            return lx, ly, rx, ry, gx, gy, gz, ax, ay, az

        # stick center correction
        lx -= c["sticks"]["lx"]
        ly -= c["sticks"]["ly"]
        rx -= c["sticks"]["rx"]
        ry -= c["sticks"]["ry"]

        # gyro bias
        gx -= c["gyro_bias"][0]
        gy -= c["gyro_bias"][1]
        gz -= c["gyro_bias"][2]

        # accel bias
        ax -= c["accel_bias"][0]
        ay -= c["accel_bias"][1]
        az -= c["accel_bias"][2]

        return lx, ly, rx, ry, gx, gy, gz, ax, ay, az

    def run(self):
        event = sdl3.SDL_Event()
        while self.running:
            while sdl3.SDL_PollEvent(ctypes.byref(event)):
                match event.type:
                    case sdl3.SDL_EVENT_QUIT:
                        self.running = False

                    case sdl3.SDL_EVENT_GAMEPAD_ADDED:
                        self.refresh_gamepads()

                    case sdl3.SDL_EVENT_GAMEPAD_REMOVED:
                        self.refresh_gamepads()

                    case sdl3.SDL_EVENT_MOUSE_BUTTON_DOWN:
                        self.mouse_click(
                            event.button.x,
                            event.button.y
                        )

            self.render()
            sdl3.SDL_Delay(REFRESH_DELAY)
        self.shutdown()

    def shutdown(self):
        for g in self.gamepads:
            g.close()

        sdl3.TTF_CloseFont(self.font)
        sdl3.SDL_DestroyRenderer(self.renderer)
        sdl3.SDL_DestroyWindow(self.window)
        sdl3.TTF_Quit()
        sdl3.SDL_Quit()
