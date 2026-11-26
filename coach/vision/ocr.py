"""Texto de la pantalla con el OCR que trae Windows (Windows.Media.Ocr, vía PyWinRT): sin modelos ni descargas.

Probado con el nombre del héroe seleccionado en el HUD (capturas reales a 1920x1080): LINA, ZEUS, SNIPER.
Si los paquetes winrt no están (o Windows no tiene OCR para el idioma), available() es False y quien lo use tira
de su plan B.
"""
import asyncio
import difflib
import logging
import re

from PIL import Image

log = logging.getLogger(__name__)
_engine = None
_failed = False


def _get_engine():
    global _engine, _failed
    if _engine is not None or _failed:
        return _engine
    try:
        from winrt.windows.media.ocr import OcrEngine
        _engine = OcrEngine.try_create_from_user_profile_languages()
        if _engine is None:
            from winrt.windows.globalization import Language
            _engine = OcrEngine.try_create_from_language(Language("en-US"))
    except Exception as ex:
        log.info("OCR de Windows no disponible: %s", ex)
        _engine = None
    _failed = _engine is None
    return _engine


def available() -> bool:
    return _get_engine() is not None


async def _recognize(img: Image.Image):
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.storage.streams import DataWriter
    rgba = img.convert("RGBA")
    writer = DataWriter()
    writer.write_bytes(rgba.tobytes("raw", "BGRA"))
    bmp = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8, rgba.width,
                                                 rgba.height, BitmapAlphaMode.PREMULTIPLIED)
    res = await _get_engine().recognize_async(bmp)
    return [[(w.text, w.bounding_rect.x, w.bounding_rect.width) for w in line.words] for line in res.lines]


def read_words(img: Image.Image, scale: int = 3) -> list[tuple[str, float]]:
    """[(palabra, x del centro en la imagen original)] de izquierda a derecha. [] si no hay OCR."""
    if not available():
        return []
    big = img.resize((img.width * scale, img.height * scale), Image.LANCZOS) if scale > 1 else img
    try:
        lines = asyncio.run(_recognize(big))
    except Exception:
        log.exception("fallo del OCR")
        return []
    words = [(t, (x + w / 2) / scale) for line in lines for t, x, w in line]
    return sorted(words, key=lambda tw: tw[1])


def _key(text: str) -> str:
    return re.sub(r"[^A-Z]", "", text.upper().replace("Ñ", "N"))


def match_hero(words: list[str], heroes) -> tuple[object | None, float]:
    """El héroe cuyo nombre encaja mejor con el texto leído (también nombres de varias palabras). (héroe, parecido)"""
    if not words:
        return None, 0.0
    texts = {_key(" ".join(words[i:j])) for i in range(len(words)) for j in range(i + 1, min(len(words), i + 3) + 1)}
    texts.discard("")
    best, score = None, 0.0
    for h in heroes:
        names = {_key(h.loc), *(_key(a) for a in getattr(h, "aliases", []) or [])}
        for t in texts:
            for n in names:
                if not n:
                    continue
                r = 1.0 if t == n else difflib.SequenceMatcher(None, t, n).ratio()
                if r > score:
                    best, score = h, r
    return best, score


__all__ = ["available", "match_hero", "read_words"]
