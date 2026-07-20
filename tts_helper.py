import pyttsx3
import threading
import queue
import logging

logger = logging.getLogger(__name__)

# Единственный воркер-поток обрабатывает очередь фраз строго последовательно.
# Это критично: pyttsx3 кеширует Engine по имени драйвера (WeakValueDictionary),
# и если вызвать pyttsx3.init() из нескольких потоков почти одновременно,
# оба потока могут получить ССЫЛКУ НА ОДИН И ТОТ ЖЕ COM-объект SAPI5 и
# одновременно дёрнуть engine.say()/runAndWait() — это не питоновское
# исключение, а нативный краш (access violation) внутри comtypes/SAPI,
# который убивает весь процесс мгновенно и без трейсбека.
# Движок при этом создаётся заново на каждую фразу (см. _worker) — SAPI5
# плохо переживает переиспользование одного Engine много раз подряд,
# поэтому единственный безопасный вариант — новый Engine на фразу,
# но гарантированно без параллелизма (один поток на всё).

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
    # ВАЖНО: движок SAPI5 у pyttsx3 плохо переживает повторное использование
    # одного и того же объекта Engine для нескольких фраз подряд — после
    # первого runAndWait() внутреннее состояние COM-прокси нередко "залипает"
    # и следующие вызовы озвучивают в тишину (без исключений). Поэтому мы
    # создаём НОВЫЙ движок на каждую фразу — но, в отличие от исходной версии,
    # делаем это строго последовательно в ОДНОМ потоке, поэтому гонки за
    # общий COM-объект между потоками (источник крашей) здесь невозможны.
    logger.debug("TTS worker: старт фонового потока")
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

    logger.debug("TTS worker: остановлен")


def _ensure_worker():
    global _worker_thread
    with _lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_worker, daemon=True)
            _worker_thread.start()


def say(text):
    """Основная функция для вызова из любого места программы.
    Кладёт текст в очередь единственного TTS-воркера, чтобы озвучки
    гарантированно не пересекались друг с другом (без пересоздания
    движка/потока на каждый вызов)."""
    logger.debug(f"TTS say: текст поставлен в очередь '{text}'")
    _ensure_worker()
    _queue.put(text)


def shutdown():
    """Опционально: аккуратно остановить TTS-поток при выходе из приложения."""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        _queue.put(None)
        _worker_thread.join(timeout=3)
        _worker_thread = None
