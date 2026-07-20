# recorder.py
import tkinter as tk
from tkinter import ttk, messagebox
import sounddevice as sd
import numpy as np
import threading
import queue
import time
import logging
import sys
import os
import subprocess
from datetime import datetime

try:
    import pyrubberband as pyrb
    RUBBERBAND_AVAILABLE = True
except ImportError:
    pyrb = None
    RUBBERBAND_AVAILABLE = False

from main import (
    LOG_FILENAME, LOG_LEVEL,
    load_settings,
    Transcriber
)

from gui import (
    WINDOW_WIDTH, WINDOW_HEIGHT,
    BUTTON_BG, BUTTON_FG,
    apply_theme, create_styled_label, create_styled_button,
    set_recording_style, reset_button_style,
    SettingsWindow, make_draggable
)

from logger_utils import setup_logging, shutdown_logging, log_time, log_system_state, log_exception
from tray_icon import TrayIcon

import tts_helper

try:
    import noisereduce as nr
    NOISEREDUCE_AVAILABLE = True
except ImportError:
    nr = None
    NOISEREDUCE_AVAILABLE = False

try:
    import scipy.signal
    SCIPY_AVAILABLE = True
except ImportError:
    scipy = None
    SCIPY_AVAILABLE = False

from silence_detector import SilenceDetector

setup_logging(LOG_FILENAME, LOG_LEVEL)
logger = logging.getLogger(__name__)

logger.info("="*60)
logger.info(f"СЕССИЯ ИНИЦИАЛИЗИРОВАНА: {datetime.now().isoformat()}")
logger.info(f"Версия Python: {sys.version}")
logger.info(f"Платформа: {sys.platform}")
logger.info(f"Запуск с аргументами: {sys.argv}")
log_system_state("Старт приложения")
logger.info("="*60)

SAMPLE_RATE = 16000

class VoiceRecorderApp:
    def __init__(self, root):
        logger.debug("Инициализация VoiceRecorderApp")
        self.root = root
        self.root.title("Диктофон → Текст")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        apply_theme(root)
        self.root.resizable(False, False)
        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)

        make_draggable(root, root)
        root.bind_all("<Button-1>", self._raise_clicked_window, add="+")

        self.settings = load_settings()
        logger.info(f"Параметры приложения загружены: {self.settings}")

        self.transcriber = None
        self.model_loaded = False
        self.is_recording = False
        self.audio_queue = queue.Queue()
        self.recorded_frames = []
        self.recording_start_time = None
        self.recording_duration = 0
        self.record_thread = None
        self.current_volume = 0.0
        self.volume_update_running = False
        self.settings_window = None

        # Инициализация детектора тишины
        threshold = self.settings.get("silence_threshold", 5.0)
        timeout = self.settings.get("silence_timeout_sec", 20.0)
        if threshold > 0 and timeout > 0:
            self.silence_detector = SilenceDetector(
                threshold=threshold,
                timeout_sec=timeout,
                callback=self.stop_recording
            )
            logger.info(f"Детектор тишины активирован (порог={threshold}%, таймаут={timeout}с)")
        else:
            self.silence_detector = None
            logger.info("Детектор тишины отключён (порог или таймаут = 0)")

        self.max_record_seconds = 600
        self.auto_stop_id = None

        # Верхняя панель: статус + настройки
        top_frame = tk.Frame(root, bg=root.cget("bg"))
        top_frame.pack(fill=tk.X, pady=5)
        make_draggable(top_frame, root)

        self.label_status = create_styled_label(top_frame, text="Загрузка модели...", font=("Arial", 14))
        self.label_status.pack(side=tk.LEFT, padx=10)
        make_draggable(self.label_status, root)

        self.btn_settings = tk.Button(
            top_frame, text="⚙️", font=("Arial", 14), command=self.open_settings,
            bg=BUTTON_BG, fg=BUTTON_FG, relief=tk.RAISED, bd=2
        )
        self.btn_settings.pack(side=tk.RIGHT, padx=10)

        # ---- СТРОКА СЧЁТЧИКОВ ----
        self.counter_frame = tk.Frame(root, bg=root.cget("bg"))
        self.counter_frame.pack(fill=tk.X, pady=(0, 5))
        make_draggable(self.counter_frame, root)

        self.label_time = create_styled_label(
            self.counter_frame,
            text="⏱ 00:00",
            font=("Arial", 12, "bold")
        )
        self.label_time.pack(side=tk.LEFT, padx=10)

        self.label_silence = create_styled_label(
            self.counter_frame,
            text="🔇 Тишина: 0.0с",
            font=("Arial", 12, "bold")
        )
        self.label_silence.pack(side=tk.RIGHT, padx=10)
        # -------------------------

        self.button_record = create_styled_button(root, text="🔴 Запись", command=self.toggle_recording)
        self.button_record.pack(pady=10)
        self.button_record.config(state="disabled")

        self.volume_var = tk.DoubleVar(value=0.0)
        self.volume_bar = ttk.Progressbar(
            root, variable=self.volume_var, maximum=100.0, length=WINDOW_WIDTH - 40,
            mode='determinate', style="Volume.Horizontal.TProgressbar"
        )
        style = ttk.Style()
        style.theme_use('default')
        style.configure("Volume.Horizontal.TProgressbar",
                        background='#32cd32', troughcolor='#2b2b2b', bordercolor='#1e1e1e',
                        lightcolor='#32cd32', darkcolor='#228b22')
        self.volume_bar.pack(pady=5)
        make_draggable(self.volume_bar, root)

        self.label_result = create_styled_label(root, text="", font=("Arial", 12))
        self.label_result.pack(pady=5)
        make_draggable(self.label_result, root)

        hotkey = self.settings.get("hotkey", "f9")
        self.tray = TrayIcon(self, root, hotkey=hotkey)
        self.tray.setup()
        self.tray.update_state('processing')

        self.load_model_async()
        log_system_state("После initialization UI")

    def _raise_clicked_window(self, event):
        try:
            event.widget.winfo_toplevel().lift()
        except tk.TclError:
            pass

    def load_model_async(self):
        self.label_status.config(text="Загрузка модели...")
        self.button_record.config(state="disabled")
        threading.Thread(target=self._load_model_thread, daemon=True).start()

    def _load_model_thread(self):
        try:
            logger.info("Подготовка к инстанцированию Whisper...")
            log_system_state("Перед аллокацией Whisper")
            self.transcriber = Transcriber(
                model_size=self.settings['model_size'],
                device=self.settings['device'],
                compute_type=self.settings['compute_type'],
                beam_size=self.settings['beam_size']
            )
            self.model_loaded = True
            self.root.after(0, self._on_model_loaded)
        except Exception as e:
            log_exception(e)
            self.root.after(0, lambda: self._on_model_error(e))

    def _on_model_loaded(self):
        hotkey = self.settings.get("hotkey", "f9")
        self.label_status.config(text=f"Нажмите 'Запись' или {hotkey}")
        self.button_record.config(state="normal")
        log_system_state("Модель успешно загружена в память")
        self.tray.update_state(False)
        tts_helper.say("Программа готова")

    def _on_model_error(self, error):
        self.label_status.config(text=f"Ошибка инициализации: {error}")
        self.tray.update_state(True)
        tts_helper.say("Ошибка загрузки модели")
        messagebox.showerror("Критическая ошибка", f"Не удалось поднять модель Whisper:\n{error}")

    def open_settings(self):
        if self.settings_window is not None:
            try:
                if self.settings_window.window.winfo_exists():
                    self.settings_window.window.lift()
                    return
            except tk.TclError:
                self.settings_window = None
        self.settings_window = SettingsWindow(self.root, self)

    def settings_window_closed(self):
        self.settings_window = None

    def _hide_all(self):
        self.root.withdraw()
        if self.settings_window and self.settings_window.window.winfo_exists():
            self.settings_window.window.withdraw()

    def _show_all(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if self.settings_window and self.settings_window.window.winfo_exists():
            self.settings_window.window.deiconify()
            self.settings_window.window.lift()

    def toggle_visibility(self):
        if self.root.state() == 'withdrawn':
            self._show_all()
        else:
            self._hide_all()

    def restart_program(self):
        logger.info("Инициирован перезапуск программы...")
        try:
            self.tray.shutdown()
        except Exception as e:
            logger.warning(f"Ошибка при остановке трея/хоткея перед рестартом: {e}")
        shutdown_logging()
        self.root.quit()
        subprocess.Popen([sys.executable] + sys.argv)
        sys.exit(0)

    def hide_window(self):
        self._hide_all()
        logger.info("Главное окно свернуто в системный трей.")

    def hotkey_toggle(self):
        logger.debug("Сработал глобальный хоткей.")
        if self.model_loaded:
            self.root.after(0, self.toggle_recording)
        else:
            logger.warning("Запись по хоткею отклонена: модель ещё не загружена.")

    @log_time
    def toggle_recording(self):
        if not self.model_loaded:
            return

        if self.record_thread and self.record_thread.is_alive() and not self.is_recording:
            logger.warning("Обнаружен висячий поток записи, попытка принудительного сброса.")
            self.stop_recording()
            return

        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        self.is_recording = True
        self.recording_start_time = time.time()
        set_recording_style(self.button_record)
        self.label_status.config(text="Запись пошла...")
        self.recorded_frames = []
        self.audio_queue = queue.Queue()

        # Сброс детектора тишины
        if self.silence_detector:
            self.silence_detector.reset()
        self.label_silence.config(text="🔇 Тишина: 0.0с")

        self.record_thread = threading.Thread(target=self.record_audio, daemon=True)
        self.record_thread.start()

        self.tray.update_state(True)
        self.volume_update_running = True
        self.current_volume = 0.0
        self._update_volume_loop()

        if self.auto_stop_id:
            self.root.after_cancel(self.auto_stop_id)
        self.auto_stop_id = self.root.after(int(self.max_record_seconds * 1000), self._auto_stop_recording)

        tts_helper.say("Запись")

    def _auto_stop_recording(self):
        if self.is_recording:
            logger.warning(f"Достигнут лимит длительности записи ({self.max_record_seconds} сек), принудительная остановка.")
            self.stop_recording()
            self.root.after(0, lambda: tts_helper.say("Лимит времени"))

    def record_audio(self):
        logger.info("Запуск фонового аудиопотока InputStream.")
        def callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Статус аудиоввода: {status}")
            self.audio_queue.put(indata.copy())
            rms = np.sqrt(np.mean(indata**2))
            self.current_volume = min(1.0, rms * 2.0) * 100.0

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=callback):
                while self.is_recording:
                    sd.sleep(50)
        except Exception as e:
            log_exception(e)
            self.root.after(0, self.handle_recording_error, e)

    def _update_volume_loop(self):
        if not self.volume_update_running:
            return
        self.volume_var.set(self.current_volume)

        # Обновление детектора тишины
        if self.silence_detector and self.is_recording:
            self.silence_detector.update(self.current_volume)

        # ---- Обновление счётчиков ----
        if self.is_recording and self.recording_start_time:
            elapsed = time.time() - self.recording_start_time
            self.label_time.config(text=f"⏱ {self._format_time(elapsed)}")
        else:
            self.label_time.config(text="⏱ 00:00")

        if self.silence_detector and self.is_recording:
            silence_dur = self.silence_detector.get_silence_duration()
            self.label_silence.config(text=f"🔇 Тишина: {silence_dur:.1f}с")
        else:
            self.label_silence.config(text="🔇 Тишина: 0.0с")
        # ---------------------------------

        self.root.after(30, self._update_volume_loop)

    def _format_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"

    def handle_recording_error(self, error):
        logger.error(f"Обработка ошибки записи: {error}")
        self.is_recording = False
        self.volume_update_running = False
        if self.auto_stop_id:
            self.root.after_cancel(self.auto_stop_id)
            self.auto_stop_id = None
        self.reset_ui()
        self.label_status.config(text="Ошибка записи")
        self.tray.update_state(False)
        messagebox.showerror("Ошибка аудиозахвата", f"Аппаратный сбой записи:\n{error}")

    def stop_recording(self):
        logger.debug("stop_recording() вызван.")
        self.is_recording = False
        self.volume_update_running = False

        if self.auto_stop_id:
            self.root.after_cancel(self.auto_stop_id)
            self.auto_stop_id = None

        self.tray.update_state('processing')

        if self.record_thread and self.record_thread.is_alive():
            logger.info("Ожидание завершения потока записи...")
            join_timeout = 2.0
            self.record_thread.join(timeout=join_timeout)

            if self.record_thread.is_alive():
                logger.error(f"Поток записи не завершился за {join_timeout} сек! Принудительный сброс sd.")
                try:
                    sd.stop()
                except Exception as e:
                    logger.error(f"Не удалось остановить sd: {e}")
            else:
                logger.info("Поток записи завершился успешно.")

        if self.recording_start_time:
            self.recording_duration = time.time() - self.recording_start_time
            logger.info(f"Запись завершена. Чистая длительность: {self.recording_duration:.2f} сек.")

        self.button_record.config(text="Обработка...", state="disabled", bg=BUTTON_BG)
        self.label_status.config(text="Сборка чанков аудио...")

        while not self.audio_queue.empty():
            self.recorded_frames.append(self.audio_queue.get())

        if self.recorded_frames:
            audio_data = np.concatenate(self.recorded_frames, axis=0)
            audio_float32 = audio_data.flatten().astype(np.float32)

            log_system_state("Перед обработкой аудио")
            audio_processed = self.apply_audio_processing(audio_float32, self.settings)

            # Добавление тишины перед и после (если настроено)
            silence_before = self.settings.get("silence_before_sec", 1.0)
            silence_after = self.settings.get("silence_after_sec", 1.0)
            if silence_before > 0 or silence_after > 0:
                sample_rate = SAMPLE_RATE
                if silence_before > 0:
                    before_samples = int(silence_before * sample_rate)
                    audio_processed = np.concatenate([np.zeros(before_samples, dtype=np.float32), audio_processed])
                    logger.info(f"Добавлено {silence_before} сек тишины в начало")
                if silence_after > 0:
                    after_samples = int(silence_after * sample_rate)
                    audio_processed = np.concatenate([audio_processed, np.zeros(after_samples, dtype=np.float32)])
                    logger.info(f"Добавлено {silence_after} сек тишины в конец")

            threading.Thread(target=self.transcribe_audio, args=(audio_processed,), daemon=True).start()
        else:
            logger.warning("Очередь аудиоданных оказалась пуста!")
            self.reset_ui()
            self.label_status.config(text="Нет данных")
            self.tray.update_state(False)

        # Сброс детектора после остановки
        if self.silence_detector:
            self.silence_detector.reset()

    @log_time
    def apply_audio_processing(self, audio, settings):
        processed = audio.copy()

        if settings.get("enable_time_stretch", False):
            if RUBBERBAND_AVAILABLE and pyrb is not None:
                try:
                    t0 = time.perf_counter()
                    rate = settings.get("speed_rate", 1.0)
                    if rate != 1.0:
                        processed = pyrb.time_stretch(processed, SAMPLE_RATE, rate)
                        processed = processed.astype(np.float32)
                        logger.info(f"Time stretch применен за {time.perf_counter() - t0:.4f} сек (коэффициент: {rate})")
                except Exception as e:
                    logger.error("Сбой во время применения pyrubberband (time stretch)!", exc_info=True)
            else:
                logger.warning("Запрос на изменение темпа пропущен (модуль pyrubberband не установлен)")

        if settings.get("noise_reduction", False):
            if NOISEREDUCE_AVAILABLE and nr is not None:
                try:
                    t0 = time.perf_counter()
                    strength = settings.get("noise_reduction_strength", 0.8)
                    processed = nr.reduce_noise(y=processed, sr=SAMPLE_RATE, prop_decrease=strength)
                    logger.info(f"Шумоподавление выполнено за {time.perf_counter() - t0:.4f} сек (сила: {strength})")
                except Exception as e:
                    logger.error("Сбой во время применения noisereduce!", exc_info=True)
            else:
                logger.warning("Запрос на шумоподавление пропущен (модуль noisereduce отсутствует)")

        gain_db = settings.get("gain_db", 0.0)
        if gain_db != 0.0:
            factor = 10 ** (gain_db / 20.0)
            processed = processed * factor
            logger.info(f"Применено усиление: +{gain_db} дБ (множитель: x{factor:.3f})")

        if settings.get("normalize", False):
            max_val = np.max(np.abs(processed))
            if max_val > 0:
                processed = processed * (0.9 / max_val)
                logger.debug("Амплитуда нормализована по пику 0.9")

        clipped = np.clip(processed, -1.0, 1.0)
        if np.any(clipped != processed):
            clipped_count = np.sum(np.abs(processed) > 1.0)
            logger.warning(f"Обнаружен клиппинг! Срезано {clipped_count} фреймов ({(clipped_count/len(processed))*100:.2f}%)")

        return clipped.astype(np.float32)

    def transcribe_audio(self, audio_data):
        try:
            logger.info("Отправка аудио в нейросеть Whisper...")
            log_system_state("Старт декодирования")

            t0 = time.time()
            text, lang, prob = self.transcriber.transcribe(audio_data)
            dt = time.time() - t0

            logger.info(f"Декодирование завершено за {dt:.3f} сек. Язык: {lang} (p={prob:.2f})")
            logger.info(f"Результат декодера: '{text}'")
            log_system_state("Финиш декодирования")

            if text.strip():
                self.root.after(0, self._copy_to_clipboard, text)
                self.root.after(0, self.update_ui_after_transcription, text, True)
            else:
                self.root.after(0, self.update_ui_after_transcription, "Распознано пусто", False)
        except Exception as e:
            log_exception(e)
            self.root.after(0, self.update_ui_after_transcription, f"Ошибка распознавания: {e}", False)
        finally:
            self.root.after(0, lambda: self.tray.update_state(False))
            import gc
            gc.collect()

    def _copy_to_clipboard(self, text):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            logger.debug("Результат скопирован во внутрисистемный буфер обмена.")
        except Exception as e:
            logger.error(f"Ошибка записи в буфер обмена: {e}", exc_info=True)

    def update_ui_after_transcription(self, text, success=True):
        self.reset_ui()
        if not success or text.startswith("Ошибка"):
            self.label_status.config(text=text)
            tts_helper.say("Ошибка")
        else:
            self.label_status.config(text="Текст в буфере обмена!")
            self.label_result.config(text=text[:100] + ("..." if len(text) > 100 else ""))
            tts_helper.say("Готово")

    def reset_ui(self):
        reset_button_style(self.button_record)
        self.label_status.config(text="Готов к записи")
        self.button_record.config(state="normal" if self.model_loaded else "disabled")
        self.volume_var.set(0.0)
        self.current_volume = 0.0
        # Сброс счётчиков
        self.label_time.config(text="⏱ 00:00")
        self.label_silence.config(text="🔇 Тишина: 0.0с")

def main():
    root = tk.Tk()
    app = VoiceRecorderApp(root)
    try:
        root.mainloop()
    finally:
        logger.info("Жизненный цикл Tkinter завершен. Закрытие приложения...")
        shutdown_logging()

if __name__ == "__main__":
    main()