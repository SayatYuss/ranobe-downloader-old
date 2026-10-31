"""Single-threaded EPUB assembly from previously downloaded chapter data."""
import html
import os
import shutil
import time

from bs4 import BeautifulSoup
from ebooklib import epub

from .utils import convert_to_webp, sanitize_filename


def _html_content(content, image_resolver):
    """Render supported content as XHTML fragments; escape external text."""
    if isinstance(content, dict) and content.get("type") == "doc":
        fragments = []
        for block in content.get("content", []):
            kind = block.get("type")
            if kind == "paragraph":
                parts = []
                for item in block.get("content", []):
                    if item.get("type") == "text":
                        text = html.escape(item.get("text", ""))
                        marks = {mark.get("type") for mark in item.get("marks", [])}
                        if "bold" in marks:
                            text = f"<strong>{text}</strong>"
                        if "italic" in marks:
                            text = f"<em>{text}</em>"
                        parts.append(text)
                fragments.append(f"<p>{''.join(parts)}</p>")
            elif kind == "image":
                for img in block.get("attrs", {}).get("images", []):
                    if img.get("image"):
                        url = image_resolver(img["image"], True)
                        if url:
                            fragments.append(f'<p><img src="{html.escape(url, quote=True)}" alt="image"/></p>')
        return "\n".join(fragments)

    if isinstance(content, str):
        soup = BeautifulSoup(content, "html.parser")
        fragments = []
        for node in soup.find_all(["p", "img"]):
            if node.name == "p":
                # Extract text rather than embedding untrusted source markup.
                fragments.append(f"<p>{html.escape(node.get_text(' ', strip=True))}</p>")
            elif node.get("src"):
                url = image_resolver(node["src"], False)
                if url:
                    fragments.append(f'<p><img src="{html.escape(url, quote=True)}" alt="image"/></p>')
        return "\n".join(fragments)
    return "<p>[Неподдерживаемый формат контента]</p>"


class EpubBuilder:
    def __init__(self, novel, *, save_images=True, image_fetcher=None, logger=None):
        self.novel = novel
        self.save_images = save_images
        self.image_fetcher = image_fetcher
        self.log = logger or (lambda message: None)
        self.book = epub.EpubBook()
        self.book.set_identifier(f"ranobe-{novel['id']}")
        self.book.set_title(novel["title"])
        self.book.set_language("ru")
        self.book.add_author(novel["authors"])
        self.chapters = []
        self.images = {}

    def _image(self, value, is_id, chapter_id):
        if not self.save_images or not self.image_fetcher:
            return None
        if is_id:
            base = f"https://ranobelib.me/uploads/ranobe/{self.novel['id']}/chapters/{chapter_id}/{value}"
            candidates = [f"{base}.{ext}" for ext in ("jpg", "png", "jpeg", "webp")]
        else:
            candidates = [value]

        for candidate in candidates:
            if candidate in self.images:
                return self.images[candidate]
            try:
                data = self.image_fetcher(candidate)
                converted = convert_to_webp(data)
                name = f"images/img_{len(self.images) + 1}.webp"
                item = epub.EpubImage()
                item.file_name = name
                item.media_type = "image/webp"
                item.content = converted
                self.book.add_item(item)
                self.images[candidate] = name
                return name
            except Exception:
                continue
        self.log(f"Не удалось загрузить изображение: {value}")
        return None

    def add_chapter(self, index, volume, number, data):
        title = f"Том {volume}, Глава {number}"
        chapter_id = data.get("id")
        content = _html_content(
            data["content"],
            lambda value, is_id: self._image(value, is_id, chapter_id),
        )
        chapter = epub.EpubHtml(title=title, file_name=f"chap_{index}.xhtml", lang="ru")
        chapter.content = f"<html><head><title>{html.escape(title)}</title></head><body><h1>{html.escape(title)}</h1>{content}</body></html>"
        self.book.add_item(chapter)
        self.chapters.append(chapter)

    def write(self, output_dir):
        if not self.chapters:
            raise ValueError("Невозможно сохранить EPUB без глав")
        os.makedirs(output_dir, exist_ok=True)
        filename = sanitize_filename(self.novel["title"]) or f"ranobe-{self.novel['id']}"
        path = os.path.join(output_dir, f"{filename}.epub")
        self.book.toc = tuple(self.chapters)
        self.book.add_item(epub.EpubNcx())
        self.book.add_item(epub.EpubNav())
        self.book.spine = ["nav", *self.chapters]

        # Write the new file completely before touching an existing copy.
        temporary = path + ".tmp"
        try:
            epub.write_epub(temporary, self.book, {})
            if os.path.exists(path):
                backup = os.path.join(output_dir, f"{filename}_backup_{time.time_ns()}.epub")
                shutil.copy2(path, backup)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return path
