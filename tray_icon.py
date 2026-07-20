# tray_icon.py
import pystray
from PIL import Image, ImageDraw
import threading
import logging
import queue

logger = logging.getLogger(__name__)

class TrayIcon:
    def __init__(self, app, root, hotkey="f9"):
        self.app = app
        self.root = root
        self.hotkey = hotkey
        self.icon = None
        self.icon_thread = None
        self.running = False
        self.is_recording = False
        self.cmd_queue = queue.Queue()

        self.create_icon_images()
        self.setup()

    def create_icon_images(self):
        size = 64
        # Зелёная иконка
        img_green = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_green)
        draw.ellipse((8, 8, size-8, size-8), fill='#32cd32', outline='#228b22', width=2)
        self.icon_green = img_green

        # Красная иконка
        img_red = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_red)
        draw.ellipse((8, 8, size-8, size-8), fill='#ff3333', outline='#cc0000', width=2)
        self.icon_red = img_red

        # Жёлтая иконка
        img_yellow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_yellow)
        draw.ellipse((8, 8, size-8, size-8), fill='#ffc107', outline='#b38600', width=2)
        self.icon_yellow = img_yellow

    def setup(self):
        # Создаём иконку с зелёным изображением
        self.icon = pystray.Icon(
            "voice_recorder",
            self.icon_green,
            f"Диктофон → Текст ({self.hotkey})",
            menu=pystray.Menu(
                pystray.MenuItem("Показать/Скрыть окно", self._toggle_window),
                pystray.MenuItem("Настройки", self._open_settings),
                pystray.MenuItem("Перезапустить", self._restart),
                pystray.MenuItem("Выход", self._quit)
            )
        )
        self.running = True
        # Запускаем иконку в отдельном потоке
        self.icon_thread = threading.Thread(target=self._run_icon, daemon=True)
        self.icon_thread.start()
        # Периодически проверяем команды из очереди (для обновления состояния)
        self._process_commands()

    def _run_icon(self):
        self.icon.run()

    def _process_commands(self):
        try:
            while True:
                cmd = self.cmd_queue.get_nowait()
                self._execute_command(cmd)
        except queue.Empty:
            pass
        if self.running:
            self.root.after(100, self._process_commands)

    def _execute_command(self, cmd):
        cmd_type = cmd[0]
        if cmd_type == 'update_state':
            self._update_state(cmd[1])
        elif cmd_type == 'quit':
            self._quit_internal()
        elif cmd_type == 'restart':
            self._restart_internal()

    def _send_command(self, cmd):
        self.cmd_queue.put(cmd)

    def update_state(self, state):
        self._send_command(('update_state', state))

    def _update_state(self, state):
        logger.debug(f"_update_state: state={state}")
        if state == 'processing':
            self.is_recording = False
            self.icon.icon = self.icon_yellow
        elif state:
            self.is_recording = True
            self.icon.icon = self.icon_red
        else:
            self.is_recording = False
            self.icon.icon = self.icon_green
        self.icon.update_menu()  # обновить меню, если нужно

    def _toggle_window(self):
        logger.debug("_toggle_window: переключение видимости через трей")
        self.root.after(0, self.app.toggle_visibility)

    def _open_settings(self):
        logger.debug("_open_settings: открытие настроек")
        self.root.after(0, self.app.open_settings)

    def _restart(self):
        logger.debug("_restart: перезапуск")
        self._send_command(('restart',))

    def _restart_internal(self):
        self.running = False
        self.icon.stop()
        self.root.after(0, self.app.restart_program)

    def _quit(self):
        logger.debug("_quit: выход")
        self._send_command(('quit',))

    def _quit_internal(self):
        self.running = False
        self.icon.stop()
        self.root.after(0, self.root.quit)

    def shutdown(self):
        self.running = False
        if self.icon:
            self.icon.stop()