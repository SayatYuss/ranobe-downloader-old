"""HTTP client for RanobeLib. No EPUB or UI dependencies."""
import time
from urllib.parse import urlparse

import requests

from .config import HEADERS
from .utils import get_slug


class RanobeLibClient:
    def __init__(self, session=None, timeout=30, retries=5):
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        self.timeout = timeout
        self.retries = retries

    def _get_json(self, url, *, params=None):
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < self.retries - 1:
                    time.sleep(min(2 ** attempt, 10))
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError):
                if attempt == self.retries - 1:
                    raise
                time.sleep(min(2 ** attempt, 10))
        raise RuntimeError("Request retries exhausted")

    def get_novel(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("ranobelib.me", "www.ranobelib.me"):
            raise ValueError("Ожидается ссылка на ranobelib.me")
        slug = get_slug(url)
        payload = self._get_json(
            f"https://api.cdnlibs.org/api/manga/{slug}",
            params={"fields[]": ["eng_name", "authors"]},
        )
        data = payload.get("data") or {}
        if not data.get("id"):
            raise ValueError("Информация о новелле не найдена")
        return {
            "id": data["id"],
            "slug": slug,
            "title": data.get("rus_name") or data.get("eng_name") or "Без названия",
            "authors": ", ".join(a.get("name", "") for a in (data.get("authors") or []) if a.get("name")) or "Неизвестный автор",
        }

    def get_chapters(self, slug):
        payload = self._get_json(f"https://api.lib.social/api/manga/{slug}/chapters")
        return [
            (str(chapter.get("volume") or "0"), str(chapter.get("number") or "0"))
            for chapter in payload.get("data", [])
        ]

    def get_chapter(self, slug, volume, number):
        payload = self._get_json(
            f"https://api.lib.social/api/manga/{slug}/chapter",
            params={"volume": volume, "number": number},
        )
        return payload.get("data")

    def get_image(self, url):
        """Fetch a public image URL, bounded by timeout."""
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or not (
            parsed.hostname == "ranobelib.me"
            or parsed.hostname.endswith(".ranobelib.me")
            or parsed.hostname == "cdnlibs.org"
            or parsed.hostname.endswith(".cdnlibs.org")
        ):
            raise ValueError("Недопустимый адрес изображения")
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.content

    def close(self):
        self.session.close()
