"""Threaded pipeline runner — launches pipeline.run_pipeline in a daemon thread."""
import logging
import threading
from pathlib import Path

from short_bot.pipeline import run_pipeline

_log = logging.getLogger("short_bot.web.runs")


def launch_pipeline(*, channel, settings, db_path: Path,
                    music_root: Path, templates_dir: Path,
                    cache_dir: Path, lock_dir: Path, logs_dir: Path,
                    trigger: str = "manual",
                    preselected_item=None,
                    curated_gem=None,
                    forced_topic: str | None = None) -> threading.Thread:
    """Start pipeline in a daemon thread. Returns the thread object.

    OTOMASYON AÇIKSA ELLE ÜRETİM DE SLOTA BAĞLANIR.

    GERÇEK HATA (ölçüldü): otomasyon açıkken "Şimdi üret"e basmak videoyu ANINDA ve
    PUBLIC yayınlıyordu — slot düzeninin tam dışında. İnsan ritmi için kurduğumuz her
    şey (taban saatler, rastgele yürüyüş, publishAt) tek tıkla deliniyordu; üstelik
    o video hiçbir slotu doldurmadığı için autopilot aynı gün bir tane DAHA üretiyordu.

    Artık: üretim yüklenmeden yapılır (defer_upload) ve video bir sonraki BOŞ slota
    bağlanır. Autopilot onu o slotun saatine zamanlar. Kullanıcı videoyu erken üretmiş
    olur, ritim bozulmaz.
    """
    ap = getattr(channel, "autopilot", None)
    autopilot_acik = ap is not None and ap.enabled

    def _runner():
        try:
            res = run_pipeline(
                channel=channel, settings=settings,
                db_path=db_path, music_root=music_root,
                templates_dir=templates_dir,
                cache_dir=cache_dir, lock_dir=lock_dir,
                logs_dir=logs_dir, trigger=trigger,
                preselected_item=preselected_item,
                curated_gem=curated_gem,
                forced_topic=forced_topic,
                defer_upload=autopilot_acik,
            )
            if autopilot_acik and res.status == "success" and res.short_id:
                _attach_to_next_slot(db_path, channel.slug, res)
        except Exception:
            # Pipeline already records its own DB row + per-run log on internal
            # failures. Anything reaching here is a top-level surprise (lock
            # dir missing, init_db failure). Log to console so it isn't lost.
            _log.exception("launch_pipeline thread crashed for %s", channel.slug)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return thread


def _attach_to_next_slot(db_path: Path, slug: str, res) -> None:
    """Elle üretilen videoyu bir sonraki BOŞ slota bağla.

    Boş slot yoksa video yüklenmez (Shorts sayfasından elle yüklenebilir) — ritim
    dışında yayınlamaktansa beklemek yeğdir.
    """
    from short_bot.db import init_db, open_slots, slot_set_status
    try:
        eng = init_db(db_path)
        bos = [s for s in open_slots(eng, slug) if s["status"] == "planned"]
        if not bos:
            _log.info("[autopilot] %s: elle üretim için boş slot yok → video "
                      "yüklenmedi (Shorts'tan elle yükleyebilirsiniz)", slug)
            return
        s = bos[0]
        slot_set_status(eng, s["id"], "produced",
                        short_id=res.short_id, run_id=res.run_id)
        _log.info("[autopilot] %s: elle üretilen video slot %s'e bağlandı → "
                  "o saatte yayınlanacak", slug, s["slot_index"])
    except Exception:
        _log.exception("[autopilot] %s: elle üretim slota bağlanamadı", slug)
