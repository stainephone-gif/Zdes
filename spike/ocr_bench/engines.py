# -*- coding: utf-8 -*-
"""
Адаптеры OCR-движков для спайка недели 1.

Каждый движок реализует один метод: read(path) -> OcrResult.
Добавить новый движок = добавить класс и строку в ENGINES.

Все движки опциональны: если библиотека или ключ не установлены, движок
сообщает о причине и исключается из прогона, остальные работают.
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field


@dataclass
class OcrResult:
    text: str
    latency_ms: int
    cost_usd: float = 0.0
    structured: dict = field(default_factory=dict)  # если движок вернул разбор
    error: str | None = None


class Engine:
    name = 'base'

    def available(self) -> str | None:
        """Возвращает причину недоступности либо None, если движок готов."""
        return None

    def read(self, path: str) -> OcrResult:
        raise NotImplementedError


# --------------------------------------------------------------------------
# 1. PaddleOCR PP-OCRv5, кириллическая модель. Локально, бесплатно.
#    pip install paddlepaddle paddleocr
# --------------------------------------------------------------------------
class PaddleEngine(Engine):
    name = 'paddle'

    def __init__(self):
        self._ocr = None

    def available(self):
        try:
            import paddleocr  # noqa: F401
        except ImportError:
            return 'pip install paddlepaddle paddleocr'
        return None

    def _lazy(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(lang='cyrillic', use_angle_cls=True, show_log=False)
        return self._ocr

    def read(self, path):
        t0 = time.time()
        try:
            raw = self._lazy().ocr(path, cls=True)
        except Exception as exc:
            return OcrResult('', int((time.time() - t0) * 1000), error=str(exc))
        lines = []
        for page in raw or []:
            for entry in page or []:
                if entry and len(entry) > 1:
                    lines.append(entry[1][0])
        return OcrResult(' '.join(lines), int((time.time() - t0) * 1000))


# --------------------------------------------------------------------------
# 2. Tesseract 5 + rus.traineddata. Локально, бесплатно, есть Android-порт.
#    apt install tesseract-ocr tesseract-ocr-rus && pip install pytesseract pillow
# --------------------------------------------------------------------------
class TesseractEngine(Engine):
    name = 'tesseract'

    def available(self):
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
        except Exception as exc:
            return f'tesseract недоступен: {exc}'
        return None

    def read(self, path):
        import pytesseract
        from PIL import Image
        t0 = time.time()
        try:
            text = pytesseract.image_to_string(Image.open(path), lang='rus')
        except Exception as exc:
            return OcrResult('', int((time.time() - t0) * 1000), error=str(exc))
        return OcrResult(text, int((time.time() - t0) * 1000))


# --------------------------------------------------------------------------
# 3. Yandex Vision OCR. Сервер, платно, хостинг в РФ.
#    Нужны YC_IAM_TOKEN и YC_FOLDER_ID.
# --------------------------------------------------------------------------
class YandexEngine(Engine):
    name = 'yandex'
    URL = 'https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText'

    def available(self):
        if not (os.getenv('YC_IAM_TOKEN') and os.getenv('YC_FOLDER_ID')):
            return 'нет YC_IAM_TOKEN / YC_FOLDER_ID'
        return None

    def read(self, path):
        import requests
        with open(path, 'rb') as fh:
            content = base64.b64encode(fh.read()).decode()
        t0 = time.time()
        try:
            resp = requests.post(
                self.URL,
                headers={
                    'Authorization': f'Bearer {os.environ["YC_IAM_TOKEN"]}',
                    'x-folder-id': os.environ['YC_FOLDER_ID'],
                    'x-data-logging-enabled': 'false',
                },
                json={'mimeType': 'JPEG', 'languageCodes': ['ru'],
                      'model': 'page', 'content': content},
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json()['result']['textAnnotation'].get('fullText', '')
        except Exception as exc:
            return OcrResult('', int((time.time() - t0) * 1000), error=str(exc))
        # Стоимость уточните по актуальному прайсу Yandex Cloud и впишите сюда.
        return OcrResult(text, int((time.time() - t0) * 1000),
                         cost_usd=float(os.getenv('YC_COST_PER_IMAGE', '0')))


# --------------------------------------------------------------------------
# 4. Google Cloud Vision. Сервер, платно.
#    Нужен GCV_API_KEY.
# --------------------------------------------------------------------------
class GoogleVisionEngine(Engine):
    name = 'gcv'
    URL = 'https://vision.googleapis.com/v1/images:annotate'

    def available(self):
        return None if os.getenv('GCV_API_KEY') else 'нет GCV_API_KEY'

    def read(self, path):
        import requests
        with open(path, 'rb') as fh:
            content = base64.b64encode(fh.read()).decode()
        t0 = time.time()
        try:
            resp = requests.post(
                self.URL,
                params={'key': os.environ['GCV_API_KEY']},
                json={'requests': [{
                    'image': {'content': content},
                    'features': [{'type': 'DOCUMENT_TEXT_DETECTION'}],
                    'imageContext': {'languageHints': ['ru']},
                }]},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()['responses'][0]
            text = payload.get('fullTextAnnotation', {}).get('text', '')
        except Exception as exc:
            return OcrResult('', int((time.time() - t0) * 1000), error=str(exc))
        return OcrResult(text, int((time.time() - t0) * 1000), cost_usd=0.0015)


# --------------------------------------------------------------------------
# 5. Claude (мультимодальная модель). Сервер, платно.
#    Возвращает не просто текст, а сразу разбор: ФИО, годы, тип связи.
#    pip install anthropic ; нужен ANTHROPIC_API_KEY либо `ant auth login`.
# --------------------------------------------------------------------------
PLAQUE_PROMPT = (
    'На фотографии — мемориальная табличка на фасаде здания. '
    'Перепиши текст таблички дословно и разбери его. '
    'Если поле не читается — оставь его пустым, ничего не додумывай и не '
    'достраивай по своим знаниям об известных людях: нам нужно то, что '
    'физически написано на табличке.'
)


PLAQUE_SCHEMA = {
    'type': 'object',
    'properties': {
        'full_text': {'type': 'string', 'description': 'текст таблички дословно'},
        'surname': {'type': 'string'},
        'first_name': {'type': 'string'},
        'patronymic': {'type': 'string'},
        'years': {'type': 'array', 'items': {'type': 'integer'}},
        'relation': {'type': 'string',
                     'enum': ['lived', 'worked', 'born', 'died', 'event', 'unknown']},
        'legible': {'type': 'boolean', 'description': 'читается ли табличка вообще'},
    },
    'required': ['full_text', 'surname', 'first_name', 'patronymic',
                 'years', 'relation', 'legible'],
    'additionalProperties': False,
}


class ClaudeEngine(Engine):
    name = 'claude'
    # Стоимость входного изображения: токенов ≈ (ширина × высота) / 750.
    # При 1024 px по длинной стороне это ~1000 токенов.
    MODEL = os.getenv('CLAUDE_MODEL', 'claude-opus-5')
    PRICE_IN, PRICE_OUT = 5.0 / 1_000_000, 25.0 / 1_000_000  # Opus 5, $/токен

    def __init__(self):
        self._client = None

    def available(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return 'pip install anthropic'
        return None

    def _lazy(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def read(self, path):
        with open(path, 'rb') as fh:
            data = base64.standard_b64encode(fh.read()).decode()
        media = 'image/png' if path.lower().endswith('.png') else 'image/jpeg'

        t0 = time.time()
        try:
            response = self._lazy().messages.create(
                model=self.MODEL,
                max_tokens=2000,
                # Это задача переписывания, а не рассуждения: низкий effort
                # заметно снижает и стоимость, и задержку.
                output_config={'effort': 'low',
                               'format': {'type': 'json_schema',
                                          'schema': PLAQUE_SCHEMA}},
                messages=[{
                    'role': 'user',
                    'content': [
                        {'type': 'image',
                         'source': {'type': 'base64', 'media_type': media, 'data': data}},
                        {'type': 'text', 'text': PLAQUE_PROMPT},
                    ],
                }],
            )
            text_block = next(b.text for b in response.content if b.type == 'text')
            parsed = json.loads(text_block)
        except Exception as exc:
            return OcrResult('', int((time.time() - t0) * 1000), error=str(exc))

        cost = (response.usage.input_tokens * self.PRICE_IN
                + response.usage.output_tokens * self.PRICE_OUT)
        # Отдаём разбор и как текст (для общего матчера), и как структуру.
        flat = ' '.join(filter(None, [
            parsed.get('full_text', ''), parsed.get('surname', ''),
            *[str(y) for y in parsed.get('years', [])],
        ]))
        return OcrResult(
            text=flat,
            latency_ms=int((time.time() - t0) * 1000),
            cost_usd=cost,
            structured=parsed,
        )


ENGINES = {
    e.name: e for e in (
        PaddleEngine(), TesseractEngine(), YandexEngine(),
        GoogleVisionEngine(), ClaudeEngine(),
    )
}
