# hotkey.py
import win32gui
import win32con
import win32api
import threading
import logging
import time

logger = logging.getLogger(__name__)

# Флаги модификаторов для RegisterHotKey (MOD_LEFT/MOD_RIGHT в win32con отсутствуют)
MOD_CONTROL = win32con.MOD_CONTROL
MOD_SHIFT = win32con.MOD_SHIFT
MOD_ALT = win32con.MOD_ALT
MOD_WIN = win32con.MOD_WIN
MOD_LEFT = 0x4000
MOD_RIGHT = 0x8000

_MODIFIER_MAP = {
    "CTRL": MOD_CONTROL,
    "CONTROL": MOD_CONTROL,
    "SHIFT": MOD_SHIFT,
    "ALT": MOD_ALT,
    "WIN": MOD_WIN,
    "WINDOWS": MOD_WIN,
}

_VK_MAP = {
    'F1': win32con.VK_F1, 'F2': win32con.VK_F2, 'F3': win32con.VK_F3,
    'F4': win32con.VK_F4, 'F5': win32con.VK_F5, 'F6': win32con.VK_F6,
    'F7': win32con.VK_F7, 'F8': win32con.VK_F8, 'F9': win32con.VK_F9,
    'F10': win32con.VK_F10, 'F11': win32con.VK_F11, 'F12': win32con.VK_F12,
    'F13': win32con.VK_F13, 'F14': win32con.VK_F14, 'F15': win32con.VK_F15,
    'F16': win32con.VK_F16, 'F17': win32con.VK_F17, 'F18': win32con.VK_F18,
    'F19': win32con.VK_F19, 'F20': win32con.VK_F20, 'F21': win32con.VK_F21,
    'F22': win32con.VK_F22, 'F23': win32con.VK_F23, 'F24': win32con.VK_F24,
    'SPACE': win32con.VK_SPACE, 'ENTER': win32con.VK_RETURN,
    'ESC': win32con.VK_ESCAPE, 'TAB': win32con.VK_TAB,
    'BACKSPACE': win32con.VK_BACK, 'DELETE': win32con.VK_DELETE,
    'INSERT': win32con.VK_INSERT, 'HOME': win32con.VK_HOME,
    'END': win32con.VK_END, 'PAGEUP': win32con.VK_PRIOR,
    'PAGEDOWN': win32con.VK_NEXT,
    'UP': win32con.VK_UP, 'DOWN': win32con.VK_DOWN,
    'LEFT': win32con.VK_LEFT, 'RIGHT': win32con.VK_RIGHT,
    'CAPSLOCK': win32con.VK_CAPITAL, 'CAPS LOCK': win32con.VK_CAPITAL,
    'NUMLOCK': win32con.VK_NUMLOCK, 'SCROLLLOCK': win32con.VK_SCROLL,
    'PAUSE': win32con.VK_PAUSE, 'BREAK': win32con.VK_PAUSE,
    'PLUS': getattr(win32con, 'VK_OEM_PLUS', 0xBB),
    'MINUS': getattr(win32con, 'VK_OEM_MINUS', 0xBD),
    'COMMA': getattr(win32con, 'VK_OEM_COMMA', 0xBC),
    'PERIOD': getattr(win32con, 'VK_OEM_PERIOD', 0xBE),
    'SLASH': getattr(win32con, 'VK_OEM_2', 0xBF),
    'BACKSLASH': getattr(win32con, 'VK_OEM_5', 0xDC),
    'SEMICOLON': getattr(win32con, 'VK_OEM_1', 0xBA),
    'APOSTROPHE': getattr(win32con, 'VK_OEM_7', 0xDE),
    'OPENBRACKET': getattr(win32con, 'VK_OEM_4', 0xDB),
    'CLOSEBRACKET': getattr(win32con, 'VK_OEM_6', 0xDD),
    'GRAVE': getattr(win32con, 'VK_OEM_3', 0xC0),
    'TILDE': getattr(win32con, 'VK_OEM_3', 0xC0),
}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _VK_MAP[_c] = ord(_c)
for _d in "0123456789":
    _VK_MAP[_d] = ord(_d)


def parse_hotkey(hotkey_str):
    """Разбирает строку хоткея вида 'f8', 'ctrl+shift+f9', 'left alt+caps lock'.

    Возвращает кортеж (vk, modifiers) для RegisterHotKey.
    При неверной строке бросает ValueError с понятным описанием.
    """
    hotkey_str = (hotkey_str or "").strip()
    if not hotkey_str:
        raise ValueError("горячая клавиша не может быть пустой")
    parts = [p.strip().upper() for p in hotkey_str.split("+")]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError("горячая клавиша не может быть пустой")

    mods = 0
    pending_side = None
    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        if not is_last:
            side = None
            token = part
            for prefix in ("LEFT ", "RIGHT "):
                if token.startswith(prefix):
                    side = MOD_LEFT if prefix == "LEFT " else MOD_RIGHT
                    token = token[len(prefix):]
                    break
            if token in ("LEFT", "RIGHT"):
                pending_side = MOD_LEFT if token == "LEFT" else MOD_RIGHT
                continue
            if token in _MODIFIER_MAP:
                mods |= _MODIFIER_MAP[token]
                if side:
                    mods |= side
                if pending_side:
                    mods |= pending_side
                    pending_side = None
                continue
            raise ValueError(f"неизвестный модификатор '{part}'")

        # Последний элемент — основная клавиша
        if part in _MODIFIER_MAP or part in ("LEFT", "RIGHT"):
            raise ValueError("комбинация должна содержать основную клавишу (например, 'ctrl+shift+f9')")
        vk = _VK_MAP.get(part)
        if vk is None:
            raise ValueError(f"неизвестная клавиша '{part}'")
        if pending_side:
            mods |= pending_side
        return vk, mods

    raise ValueError("комбинация должна содержать основную клавишу (например, 'ctrl+shift+f9')")


class HotkeyHandler:
    def __init__(self, callback, hotkey_str="F3"):
        self.callback = callback
        self.hotkey_str = hotkey_str
        self.hwnd = None
        self.hotkey_id = 1
        self.thread = None
        self.running = False
        self.registered = False
        self.error_message = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread = threading.Thread(target=self._thread_func, daemon=True)
        self.thread.start()
        logger.info("HotkeyHandler запущен")

    def stop(self):
        self.running = False
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        logger.info("HotkeyHandler остановлен")

    def _thread_func(self):
        try:
            # 1. Создаём скрытое окно
            wc = win32gui.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName = f"HotkeyHandlerWindow_{id(self)}"
            wc.lpfnWndProc = self._wnd_proc
            class_atom = win32gui.RegisterClass(wc)
            self.hwnd = win32gui.CreateWindow(
                class_atom, "HotkeyHandlerWindow",
                win32con.WS_OVERLAPPED,
                0, 0, 0, 0,
                0, 0,
                wc.hInstance,
                None
            )
            win32gui.UpdateWindow(self.hwnd)
            logger.debug(f"Окно хоткея создано, hwnd={self.hwnd}")

            # 2. Регистрируем хоткей
            try:
                vk, mods = parse_hotkey(self.hotkey_str)
            except ValueError as e:
                self.error_message = str(e)
                logger.error(f"Неверная комбинация клавиш '{self.hotkey_str}': {e}")
                win32gui.DestroyWindow(self.hwnd)
                return
            try:
                win32gui.RegisterHotKey(self.hwnd, self.hotkey_id, mods, vk)
                self.registered = True
                logger.info(f"Хоткей {self.hotkey_str} зарегистрирован в HotkeyHandler")
            except Exception as e:
                self.error_message = str(e)
                logger.error(f"Ошибка регистрации хоткея: {e}")

            # 3. Цикл обработки сообщений (без MsgWaitForMultipleObjects)
            while self.running:
                win32gui.PumpWaitingMessages()
                if not win32gui.IsWindow(self.hwnd):
                    break
                time.sleep(0.02)  # небольшая задержка, чтобы не грузить процессор

        except Exception as e:
            logger.critical(f"Критическая ошибка в потоке хоткея: {e}", exc_info=True)
        finally:
            # 4. Очистка
            if self.registered:
                try:
                    win32gui.UnregisterHotKey(self.hwnd, self.hotkey_id)
                except:
                    pass
            if self.hwnd and win32gui.IsWindow(self.hwnd):
                win32gui.DestroyWindow(self.hwnd)
            logger.debug("HotkeyHandler поток завершён")

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
        elif msg == 0x0312:  # WM_HOTKEY
            logger.debug("WM_HOTKEY получен")
            if self.callback:
                try:
                    self.callback()
                except Exception as e:
                    logger.error(f"Ошибка в callback хоткея: {e}")
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
