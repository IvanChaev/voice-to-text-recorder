# gui.py
import tkinter as tk
from tkinter import messagebox, ttk
import os
import sys
import logging
import shutil
from main import load_settings, save_settings

# --- Цветовая схема (тёмная тема) ---
BG_COLOR = "#1e1e1e"
FG_COLOR = "#32cd32"
BUTTON_BG = "#2b2b2b"
BUTTON_FG = FG_COLOR
BUTTON_ACTIVE_BG = "#3a3a3a"
BUTTON_ACTIVE_FG = "#00ff00"
RECORDING_BG = "#8b0000"

ENTRY_BG = "#3a3a3a"
ENTRY_FG = FG_COLOR
ENTRY_BD = 2
ENTRY_RELIEF = "solid"
CHECK_BG = BG_COLOR
CHECK_FG = FG_COLOR

WINDOW_WIDTH = 600
WINDOW_HEIGHT = 270
BUTTON_FONT_SIZE = 31
LABEL_FONT_SIZE = 14
BUTTON_WIDTH = 15
BUTTON_RELIEF = "raised"
BUTTON_BD = 4

STARTUP_FOLDER = os.path.join(os.environ['APPDATA'],
                              'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
STARTUP_BAT_NAME = "my_voice_project_autostart.bat"

logger = logging.getLogger(__name__)

def apply_theme(root):
    root.configure(bg=BG_COLOR)

def make_draggable(widget, window):
    ignored_widgets = (tk.Scale, tk.Entry, tk.Spinbox, tk.Button, tk.Checkbutton, ttk.Progressbar)

    def _start_move(event):
        if isinstance(event.widget, ignored_widgets):
            return
        window._drag_offset_x = event.x_root - window.winfo_x()
        window._drag_offset_y = event.y_root - window.winfo_y()

    def _do_move(event):
        if isinstance(event.widget, ignored_widgets):
            return
        if not hasattr(window, "_drag_offset_x"):
            return
        x = event.x_root - window._drag_offset_x
        y = event.y_root - window._drag_offset_y
        window.geometry(f"+{x}+{y}")

    widget.bind("<Button-1>", _start_move)
    widget.bind("<B1-Motion>", _do_move)

def create_styled_label(parent, text, **kwargs):
    defaults = {
        "bg": BG_COLOR,
        "fg": FG_COLOR,
        "font": ("Arial", LABEL_FONT_SIZE),
        "wraplength": WINDOW_WIDTH - 40,
        "justify": "left"
    }
    defaults.update(kwargs)
    return tk.Label(parent, text=text, **defaults)

def create_styled_button(parent, text, command, **kwargs):
    defaults = {
        "font": ("Arial", BUTTON_FONT_SIZE, "bold"),
        "bg": BUTTON_BG,
        "fg": BUTTON_FG,
        "activebackground": BUTTON_ACTIVE_BG,
        "activeforeground": BUTTON_ACTIVE_FG,
        "width": BUTTON_WIDTH,
        "relief": BUTTON_RELIEF,
        "bd": BUTTON_BD
    }
    defaults.update(kwargs)
    return tk.Button(parent, text=text, command=command, **defaults)

def set_recording_style(button):
    button.config(text="⏹ Стоп", bg=RECORDING_BG, activebackground="#a00000")

def reset_button_style(button):
    button.config(text="🔴 Запись", bg=BUTTON_BG, fg=BUTTON_FG, state="normal")

class SettingsWindow:
    def __init__(self, parent, app):
        logger.debug("SettingsWindow.__init__: создание окна настроек")
        self.parent = parent
        self.app = app
        self.settings = load_settings()
        self.original_settings = self.settings.copy()

        self.window = tk.Toplevel(parent)
        self.window.title("Настройки")
        self.window.geometry("440x820")
        self.window.resizable(False, False)
        apply_theme(self.window)
        self.window.grid_propagate(False)
        self.window.pack_propagate(False)

        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        self.device_var = tk.StringVar(value=self.settings.get("device", "cuda"))
        self.beam_size_var = tk.StringVar(value=str(self.settings.get("beam_size", 5)))
        self.autostart_var = tk.BooleanVar(value=self.settings.get("autostart", False))
        self.hotkey_var = tk.StringVar(value=self.settings.get("hotkey", "left alt+caps lock"))
        self.gain_var = tk.DoubleVar(value=self.settings.get("gain_db", 10.0))
        self.normalize_var = tk.BooleanVar(value=self.settings.get("normalize", True))
        self.noise_reduction_var = tk.BooleanVar(value=self.settings.get("noise_reduction", False))
        self.noise_strength_var = tk.DoubleVar(value=self.settings.get("noise_reduction_strength", 0.8))
        self.time_stretch_var = tk.BooleanVar(value=self.settings.get("enable_time_stretch", False))
        self.speed_rate_var = tk.DoubleVar(value=self.settings.get("speed_rate", 1.0))
        self.silence_before_var = tk.DoubleVar(value=self.settings.get("silence_before_sec", 1.0))
        self.silence_after_var = tk.DoubleVar(value=self.settings.get("silence_after_sec", 1.0))
        self.silence_threshold_var = tk.DoubleVar(value=self.settings.get("silence_threshold", 5.0))
        self.silence_timeout_var = tk.DoubleVar(value=self.settings.get("silence_timeout_sec", 20.0))

        self.create_widgets()
        logger.debug("SettingsWindow.__init__: завершено")

    def on_close(self):
        logger.debug("SettingsWindow.on_close: закрытие окна")
        self.app.settings_window_closed()
        self.window.destroy()

    def create_widgets(self):
        main_frame = tk.Frame(self.window, bg=BG_COLOR)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        make_draggable(self.window, self.window)
        make_draggable(main_frame, self.window)

        row = 0

        # Устройство
        lbl_device = tk.Label(main_frame, text="Устройство:", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 11, "bold"))
        make_draggable(lbl_device, self.window)
        lbl_device.grid(row=row, column=0, sticky=tk.W, pady=5)
        device_combo = tk.OptionMenu(main_frame, self.device_var, "cuda", "cpu")
        device_combo.config(bg=ENTRY_BG, fg=ENTRY_FG, relief=ENTRY_RELIEF, bd=ENTRY_BD, highlightthickness=0, width=10)
        device_combo.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        row += 1

        # Beam size
        lbl_beam = tk.Label(main_frame, text="Beam size:", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 11, "bold"))
        make_draggable(lbl_beam, self.window)
        lbl_beam.grid(row=row, column=0, sticky=tk.W, pady=5)
        beam_spin = tk.Spinbox(main_frame, from_=1, to=20, textvariable=self.beam_size_var, width=11, bg=ENTRY_BG, fg=ENTRY_FG, relief=ENTRY_RELIEF, bd=ENTRY_BD, highlightthickness=0)
        beam_spin.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        row += 1

        # Горячая клавиша
        lbl_hotkey = tk.Label(main_frame, text="Горячая клавиша:", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 11, "bold"))
        make_draggable(lbl_hotkey, self.window)
        lbl_hotkey.grid(row=row, column=0, sticky=tk.W, pady=5)
        hotkey_entry = tk.Entry(main_frame, textvariable=self.hotkey_var, width=20, bg=ENTRY_BG, fg=ENTRY_FG, relief=ENTRY_RELIEF, bd=ENTRY_BD, highlightthickness=0)
        hotkey_entry.grid(row=row, column=1, sticky=tk.EW, padx=10, pady=5)
        row += 1
        lbl_hotkey_hint = tk.Label(main_frame, text="Формат: f9, ctrl+shift+r, left alt+caps lock", bg=BG_COLOR, fg="#888888", font=("Arial", 9, "italic"))
        make_draggable(lbl_hotkey_hint, self.window)
        lbl_hotkey_hint.grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(0, 10))
        row += 1

        # Автозапуск
        autostart_check = tk.Checkbutton(main_frame, text="Автозапуск с системой", variable=self.autostart_var, bg=CHECK_BG, fg=CHECK_FG, selectcolor=BG_COLOR, activebackground=BG_COLOR, activeforeground=FG_COLOR, font=("Arial", 11, "bold"))
        autostart_check.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        row += 1

        # Заголовок аудиообработки
        lbl_audio_title = tk.Label(main_frame, text="Аудиообработка", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 12, "bold", "underline"))
        make_draggable(lbl_audio_title, self.window)
        lbl_audio_title.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        row += 1

        # Усиление звука
        lbl_gain = tk.Label(main_frame, text="Усиление (дБ):", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 11))
        make_draggable(lbl_gain, self.window)
        lbl_gain.grid(row=row, column=0, sticky=tk.W, pady=5)
        gain_spin = tk.Spinbox(main_frame, from_=-20, to=20, increment=0.5, textvariable=self.gain_var, width=11, bg=ENTRY_BG, fg=ENTRY_FG, relief=ENTRY_RELIEF, bd=ENTRY_BD, highlightthickness=0)
        gain_spin.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        row += 1

        # Нормализация
        normalize_check = tk.Checkbutton(main_frame, text="Нормализация (пик к 0.9)", variable=self.normalize_var, bg=CHECK_BG, fg=CHECK_FG, selectcolor=BG_COLOR, activebackground=BG_COLOR, activeforeground=FG_COLOR, font=("Arial", 11))
        normalize_check.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        row += 1

        # Шумоподавление
        noise_check = tk.Checkbutton(main_frame, text="Шумоподавление (вкл)", variable=self.noise_reduction_var, bg=CHECK_BG, fg=CHECK_FG, selectcolor=BG_COLOR, activebackground=BG_COLOR, activeforeground=FG_COLOR, font=("Arial", 11))
        noise_check.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        row += 1

        # Сила шумоподавления
        lbl_noise_strength = tk.Label(main_frame, text="Сила шумоподавления:", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 11))
        make_draggable(lbl_noise_strength, self.window)
        lbl_noise_strength.grid(row=row, column=0, sticky=tk.W, pady=5)
        noise_strength_scale = tk.Scale(main_frame, from_=0.0, to=1.0, resolution=0.05,
                                        orient=tk.HORIZONTAL, variable=self.noise_strength_var,
                                        bg=ENTRY_BG, fg=FG_COLOR, highlightthickness=0,
                                        length=150, troughcolor=BUTTON_BG)
        noise_strength_scale.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        row += 1

        # --- ЭЛЕМЕНТЫ УПРАВЛЕНИЯ СКОРОСТЬЮ ---
        time_stretch_check = tk.Checkbutton(main_frame, text="Изменение темпа речи (вкл)",
                                            variable=self.time_stretch_var, bg=CHECK_BG, fg=CHECK_FG,
                                            selectcolor=BG_COLOR, activebackground=BG_COLOR,
                                            activeforeground=FG_COLOR, font=("Arial", 11))
        time_stretch_check.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        row += 1

        lbl_speed_rate = tk.Label(main_frame, text="Коэффициент темпа:", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 11))
        make_draggable(lbl_speed_rate, self.window)
        lbl_speed_rate.grid(row=row, column=0, sticky=tk.W, pady=5)

        speed_rate_scale = tk.Scale(main_frame, from_=0.5, to=2.0, resolution=0.05,
                                    orient=tk.HORIZONTAL, variable=self.speed_rate_var,
                                    bg=ENTRY_BG, fg=FG_COLOR, highlightthickness=0,
                                    length=150, troughcolor=BUTTON_BG)
        speed_rate_scale.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        row += 1

        # Паузы перед/после записи
        lbl_silence_before = tk.Label(main_frame, text="Пауза перед (сек):", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 11))
        make_draggable(lbl_silence_before, self.window)
        lbl_silence_before.grid(row=row, column=0, sticky=tk.W, pady=5)
        silence_before_spin = tk.Spinbox(main_frame, from_=0.0, to=5.0, increment=0.1,
                                         textvariable=self.silence_before_var, width=11,
                                         bg=ENTRY_BG, fg=ENTRY_FG, relief=ENTRY_RELIEF,
                                         bd=ENTRY_BD, highlightthickness=0)
        silence_before_spin.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        row += 1

        lbl_silence_after = tk.Label(main_frame, text="Пауза после (сек):", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 11))
        make_draggable(lbl_silence_after, self.window)
        lbl_silence_after.grid(row=row, column=0, sticky=tk.W, pady=5)
        silence_after_spin = tk.Spinbox(main_frame, from_=0.0, to=5.0, increment=0.1,
                                        textvariable=self.silence_after_var, width=11,
                                        bg=ENTRY_BG, fg=ENTRY_FG, relief=ENTRY_RELIEF,
                                        bd=ENTRY_BD, highlightthickness=0)
        silence_after_spin.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        row += 1

        # ========== НОВЫЙ РАЗДЕЛ: АВТООСТАНОВКА ПО ТИШИНЕ ==========
        lbl_auto_title = tk.Label(main_frame, text="Автоостановка по тишине", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 12, "bold", "underline"))
        make_draggable(lbl_auto_title, self.window)
        lbl_auto_title.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        row += 1

        lbl_threshold = tk.Label(main_frame, text="Порог громкости (%):", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 11))
        make_draggable(lbl_threshold, self.window)
        lbl_threshold.grid(row=row, column=0, sticky=tk.W, pady=5)
        threshold_spin = tk.Spinbox(main_frame, from_=0.0, to=100.0, increment=0.5,
                                    textvariable=self.silence_threshold_var, width=11,
                                    bg=ENTRY_BG, fg=ENTRY_FG, relief=ENTRY_RELIEF,
                                    bd=ENTRY_BD, highlightthickness=0)
        threshold_spin.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        row += 1

        lbl_timeout = tk.Label(main_frame, text="Время тишины (сек):", bg=BG_COLOR, fg=FG_COLOR, font=("Arial", 11))
        make_draggable(lbl_timeout, self.window)
        lbl_timeout.grid(row=row, column=0, sticky=tk.W, pady=5)
        timeout_spin = tk.Spinbox(main_frame, from_=0.0, to=60.0, increment=0.5,
                                  textvariable=self.silence_timeout_var, width=11,
                                  bg=ENTRY_BG, fg=ENTRY_FG, relief=ENTRY_RELIEF,
                                  bd=ENTRY_BD, highlightthickness=0)
        timeout_spin.grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        row += 1
        # ============================================================

        # ---------- ДИНАМИЧЕСКАЯ ИНФО-СТРОКА ----------
        current_model = self.settings.get("model_size", "medium")
        current_compute = "float32" if self.device_var.get() == "cpu" else "int8_float16"
        info_text = f"Модель: {current_model} | Вычисления: {current_compute} | Частота: 16000 Гц"
        lbl_info = tk.Label(main_frame, text=info_text, bg=BG_COLOR, fg="#888888", font=("Arial", 9), justify=tk.CENTER)
        make_draggable(lbl_info, self.window)
        lbl_info.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=10)
        row += 1

        btn_frame = tk.Frame(main_frame, bg=BG_COLOR)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(10, 0))
        btn_save = tk.Button(btn_frame, text="Сохранить", command=self.save_settings, font=("Arial", 11, "bold"), bg=BUTTON_BG, fg=FG_COLOR, width=12, relief="raised", bd=2)
        btn_save.pack(side=tk.LEFT, padx=10)
        btn_cancel = tk.Button(btn_frame, text="Отмена", command=self.on_close, font=("Arial", 11), bg=BUTTON_BG, fg="#ff4500", width=12, relief="raised", bd=2)
        btn_cancel.pack(side=tk.LEFT, padx=10)

        main_frame.columnconfigure(1, weight=1)

    def save_settings(self):
        logger.debug("SettingsWindow.save_settings: начало сохранения")
        try:
            new_settings = self.settings.copy()
            new_settings["device"] = self.device_var.get()
            new_settings["beam_size"] = int(self.beam_size_var.get())
            new_settings["autostart"] = self.autostart_var.get()
            new_settings["hotkey"] = self.hotkey_var.get().strip()
            new_settings["gain_db"] = float(self.gain_var.get())
            new_settings["normalize"] = self.normalize_var.get()
            new_settings["noise_reduction"] = self.noise_reduction_var.get()
            new_settings["noise_reduction_strength"] = float(self.noise_strength_var.get())
            
            new_settings["enable_time_stretch"] = self.time_stretch_var.get()
            new_settings["speed_rate"] = float(self.speed_rate_var.get())

            new_settings["silence_before_sec"] = float(self.silence_before_var.get())
            new_settings["silence_after_sec"] = float(self.silence_after_var.get())

            new_settings["silence_threshold"] = float(self.silence_threshold_var.get())
            new_settings["silence_timeout_sec"] = float(self.silence_timeout_var.get())

            if not new_settings["hotkey"]:
                raise ValueError("Горячая клавиша не может быть пустой.")
            
            if new_settings["device"] == "cpu":
                new_settings["compute_type"] = "float32"
            else:
                new_settings["compute_type"] = "int8_float16"
            
            if new_settings["beam_size"] < 1:
                raise ValueError("Beam size должен быть >= 1")

            self._update_autostart(new_settings["autostart"])
            save_settings(new_settings)

            logger.info(f"Настройки сохранены: device={new_settings['device']}, beam_size={new_settings['beam_size']}, "
                        f"hotkey='{new_settings['hotkey']}', autostart={new_settings['autostart']}, "
                        f"gain_db={new_settings['gain_db']}, normalize={new_settings['normalize']}, "
                        f"noise_reduction={new_settings['noise_reduction']}, noise_strength={new_settings['noise_reduction_strength']}, "
                        f"enable_time_stretch={new_settings['enable_time_stretch']}, speed_rate={new_settings['speed_rate']}, "
                        f"silence_before={new_settings['silence_before_sec']}, silence_after={new_settings['silence_after_sec']}, "
                        f"silence_threshold={new_settings['silence_threshold']}, silence_timeout={new_settings['silence_timeout_sec']}, "
                        f"compute_type={new_settings['compute_type']}")

            keys_to_check = [k for k in new_settings if k != "autostart"]
            important_changed = any(new_settings.get(k) != self.original_settings.get(k) for k in keys_to_check)

            self.on_close()

            if important_changed:
                messagebox.showinfo("Успех", "Настройки сохранены. Программа будет перезапущена для применения изменений.")
                self.app.restart_program()
            else:
                messagebox.showinfo("Успех", "Настройки обновлены (перезапуск не требуется).")
        except Exception as e:
            logger.error(f"Ошибка при сохранении настроек: {e}", exc_info=True)
            messagebox.showerror("Ошибка", f"Неверные данные:\n{e}")

    def _update_autostart(self, enable):
        logger.debug(f"_update_autostart: enable={enable}")
        dest_bat = os.path.join(STARTUP_FOLDER, STARTUP_BAT_NAME)
        if enable:
            try:
                project_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                # Ищем pythonw.exe универсально
                pythonw_path = sys.executable.replace("python.exe", "pythonw.exe")
                if not os.path.exists(pythonw_path):
                    pythonw_path = shutil.which("pythonw")
                if not pythonw_path or not os.path.exists(pythonw_path):
                    raise FileNotFoundError(
                        "Не удалось найти pythonw.exe. "
                        "Убедитесь, что Python добавлен в PATH, или укажите путь вручную в файле start.bat"
                    )
                bat_content = f"""@echo off
cd /d "{project_dir}"
if exist __pycache__ rmdir /s /q __pycache__
powershell -Command "Start-Process -FilePath '{pythonw_path}' -ArgumentList 'main.py'"
exit
"""
                with open(dest_bat, 'w', encoding='utf-8') as f:
                    f.write(bat_content)
                logger.info(f"Автозапуск включён: создан {dest_bat}")
            except Exception as e:
                logger.error(f"Не удалось включить автозапуск: {e}", exc_info=True)
                raise RuntimeError(f"Не удалось включить автозапуск: {e}")
        else:
            if os.path.exists(dest_bat):
                os.remove(dest_bat)
                logger.info(f"Автозапуск отключён: удалён {dest_bat}")