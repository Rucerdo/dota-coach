"""Lee los consejos en voz alta con la voz de Windows (SAPI). Opcional: 'tts': true en la configuración."""
import logging
import queue
import threading

log = logging.getLogger(__name__)


class Speaker:
    def __init__(self):
        self.q: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text: str):
        self.q.put(text)

    def _run(self):
        try:
            import comtypes
            import comtypes.client
            comtypes.CoInitialize()
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
        except Exception:
            log.exception("voz de Windows no disponible")
            return
        while True:
            text = self.q.get()
            try:
                voice.Speak(text, 0)  # síncrono dentro de este hilo: los consejos no se pisan
            except Exception:
                log.exception("error al leer en voz alta")
