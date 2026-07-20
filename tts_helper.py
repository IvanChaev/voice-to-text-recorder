import pyttsx3
import threading
import queue
import logging
import pythoncom   # добавлен для явной инициализации COM

logger = logging.getLogger(__name__)

_queue = queue.Queue()
_worker_thread = None
_lock = threading.Lock()


def _init_engine():
    engine = pyttsx3.init()
    engine.setProperty('rate', 185)
    voices = engine.getProperty('voices')
    for voice in voices:
        if "irina" in voice.name.lower():
            engine.setProperty('voice', voice.id)
            break
    return engine


def _worker():
    logger.debug("TTS worker: старт фонового потока")
    # Явная инициализация COM для этого потока
    pythoncom.CoInitialize()
    try:
        while True:
            text = _queue.get()
            if text is None:  # сигнал остановки
                _queue.task_done()
                break
            logger.debug(f"TTS worker: озвучка '{text}'")
            try:
                engine = _init_engine()
                engine.say(text)
                engine.runAndWait()
                engine.stop()
                del engine
            except Exception as e:
                logger.error(f"[TTS Error]: {e}", exc_info=True)
            finally:
                _queue.task_done()
    finally:
        pythoncom.CoUninitialize()
        logger.debug("TTS worker: остановлен")


def _ensure_worker():
    global _worker_thread
    with _lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_worker, daemon=True)
            _worker_thread.start()


def say(text):
    logger.debug(f"TTS say: текст поставлен в очередь '{text}'")
    _ensure_worker()
    _queue.put(text)


def shutdown():
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        _queue.put(None)
        _worker_thread.join(timeout=3)
        _worker_thread = None