"""Downloading orchestration, independent of Tkinter and EPUB internals."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .epub_builder import EpubBuilder
from .ranobelib_client import RanobeLibClient


def run_download(novel_url, save_images, output_dir, log_queue):
    """Compatibility entry point for the existing desktop application."""
    def log(message):
        log_queue.put(message)

    started = time.monotonic()
    client = RanobeLibClient()
    try:
        novel = client.get_novel(novel_url)
        log(f"Название: {novel['title']}")
        log(f"Автор(ы): {novel['authors']}")
        chapters = client.get_chapters(novel["slug"])
        if not chapters:
            log("Главы не найдены")
            return False
        log(f"Найдено глав: {len(chapters)}")

        # Network requests are parallel; EPUB mutation happens only on this thread.
        results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            tasks = {
                executor.submit(client.get_chapter, novel["slug"], volume, number): (idx, volume, number)
                for idx, (volume, number) in enumerate(chapters, start=1)
            }
            for future in as_completed(tasks):
                idx, volume, number = tasks[future]
                try:
                    data = future.result()
                    if not data or not data.get("content"):
                        raise ValueError("Пустое содержимое главы")
                    results[idx] = data
                    log(f"Загружена глава {idx}/{len(chapters)}")
                except Exception as exc:
                    log(f"Не удалось загрузить главу {volume}-{number}: {exc}")

        builder = EpubBuilder(novel, save_images=save_images, image_fetcher=client.get_image, logger=log)
        for idx, (volume, number) in enumerate(chapters, start=1):
            if idx in results:
                builder.add_chapter(idx, volume, number, results[idx])

        if not results:
            log("Не удалось загрузить ни одной главы")
            return False

        path = builder.write(output_dir)
        log(f"Книга сохранена: {path}")
        log(f"Загружено глав: {len(results)}/{len(chapters)}")
        if len(results) != len(chapters):
            log("Внимание: EPUB неполный, часть глав не загружена")
        log(f"Время: {time.monotonic() - started:.1f} сек.")
        return len(results) == len(chapters)
    except Exception as exc:
        log(f"Ошибка загрузки: {exc}")
        return False
    finally:
        client.close()
