"""Claude'un yeni arketip TASARLAMASI — kapılı.

Bugün Claude palet, font, punto, banner/vurgu/çip stili ve 8000 karaktere kadar
`custom_css` üretiyor ama arketipi 40 hazır `.j2`'den SEÇİYOR. Bu modül onu
yeni şablon YAZABİLİR hâle getirir; tutarsızlık korkusunun cevabı LLM'i
kısıtlamak değil, çıktıyı DENETLEMEK (bkz. archetype_gate).

DÖNGÜ:
    1. Claude şablonu yazar (serbest HTML + CSS)
    2. yapı kapısı — bedava; geçmezse SEBEP LLM'e geri yazılır
    3. render — chromium, ÜÇ UÇ METİNLE
    4. vision kapısı — üç kareye bakar
    5. geçerse kaydedilir; en fazla `TUR` deneme, sonra kaydetmeden pes edilir

KAYDETMEDEN PES ETMEK ŞART: geçen her şablon diskte KALICI dosya olur.
Üç turda düzelmeyen bir şablonu "olsun bari" diye yazmak, 40 kalıbın yanına
41'inci bozuk kalıbı eklemek ve onu kimsenin temizlememesi demektir.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from short_bot.archetype_gate import UC_METINLER, vision_kapisi, yapi_kapisi

log = logging.getLogger(__name__)

TUR = 3
# Prompt'a örnek olarak konan çalışan şablonlar. İkisi bilinçli: biri sade
# (newscast), biri zengin (flas). Tek örnek verince LLM onu kopyalıyor.
ORNEK_SABLONLAR = ("newscast", "flas")


@dataclass(frozen=True)
class TasarimSonucu:
    ok: bool
    slug: str = ""
    sebep: str = ""
    tur: int = 0


def _prompt(niyet: str, spec_metni: str, ornekler: dict[str, str],
            onceki_hata: str = "") -> str:
    p = [
        "Bir YouTube Shorts kanalı için YENİ bir görsel şablon (Jinja2 + HTML + CSS) yaz.",
        "",
        f"İSTENEN GÖRÜNÜM: {niyet}",
        "",
        "ZORUNLU SÖZLEŞME (uymayan şablon reddedilir):",
        spec_metni,
        "",
        "ÇALIŞAN ÖRNEKLER — yapıyı bunlardan al, GÖRÜNÜMÜ kopyalama:",
    ]
    for ad, icerik in ornekler.items():
        p += [f"--- {ad}.html.j2 ---", icerik, ""]
    if onceki_hata:
        p += ["", "ÖNCEKİ DENEMEN REDDEDİLDİ. Sebep:", onceki_hata,
              "Bunu düzelt ve şablonun TAMAMINI yeniden yaz.", ""]
    p += ["", "Yalnız şablonun kendisini döndür: <!DOCTYPE html> ile başla, "
          "</html> ile bitir. Açıklama yazma."]
    return "\n".join(p)


def _sablonu_ayikla(ham: str) -> str:
    """LLM markdown çiti ya da açıklama eklemiş olabilir."""
    m = re.search(r"<!DOCTYPE html>.*?</html>", ham, re.S | re.I)
    return m.group(0) if m else ham.strip()


def _slugify(ad: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (ad or "")).strip("-").lower()
    return s or "arketip"


def tasarla(niyet: str, *, ad: str, templates_dir: Path, settings,
            metin_llm: Callable[[str], str],
            vision_call=None,
            render_fn: Callable[..., Sequence[Path]] | None = None,
            tur: int = TUR) -> TasarimSonucu:
    """Yeni bir arketip şablonu üretir ve kapılardan geçirir.

    `metin_llm`: prompt alır, ham metin döndürür (şema YOK — çıktı HTML).
    `render_fn`: (html_yolu, script) -> üretilen PNG'ler. Enjekte edilebilir
                 olması testin Playwright'a bağımlı olmamasını sağlar.
    """
    templates_dir = Path(templates_dir)
    spec_yolu = Path("TEMPLATE-SPEC.md")
    spec_metni = (spec_yolu.read_text(encoding="utf-8")[:6000]
                  if spec_yolu.exists() else
                  "TEMPLATE-SPEC bulunamadı; örneklerdeki yapıyı birebir izle.")
    ornekler = {}
    for o in ORNEK_SABLONLAR:
        p = templates_dir / f"{o}.html.j2"
        if p.exists():
            ornekler[o] = p.read_text(encoding="utf-8")

    slug = _slugify(ad)
    hata = ""
    for deneme in range(1, tur + 1):
        try:
            html = _sablonu_ayikla(metin_llm(_prompt(niyet, spec_metni, ornekler, hata)))
        except Exception as e:   # noqa: BLE001 — modele ulaşılamadı
            return TasarimSonucu(False, sebep=f"Modele ulaşılamadı: {e}", tur=deneme)

        ok, hata = yapi_kapisi(html)
        if not ok:
            log.info(f"[arketip] tur {deneme}: yapı kapısı reddetti — {hata[:120]}")
            continue

        # Render + vision yalnız yapı kapısını geçenler için: chromium açmak
        # pahalı, eksik slotlu şablon için harcanmasın.
        if render_fn is None:
            return TasarimSonucu(False, sebep="Render çağrısı verilmedi.", tur=deneme)
        # ADAY, PAYLAŞILAN PARÇALARIN YANINDA RENDER EDİLİR. `renderer.py`
        # Jinja arama yolunu şablonun BULUNDUĞU dizin yapıyor
        # (FileSystemLoader(template_path.parent)); boş bir temp dizininde
        # `{% include "_auto_fit.js.j2" %}` çözülemiyor.
        #
        # İLK GERÇEK KOŞUDA (2026-08-21) tam bu oldu: üç tur da
        # "'_auto_fit.js.j2' not found in search path" ile düştü — yani bu
        # akış hiç çalışmamıştı. Testler sahte `render_fn` enjekte ettiği
        # için görünmüyordu.
        #
        # Kopya temp dizine alınır, `templates_dir`e geçici dosya YAZILMAZ:
        # orası kullanıcının deposu.
        with tempfile.TemporaryDirectory() as tmp:
            for paylasilan in templates_dir.glob("_*.j2"):
                (Path(tmp) / paylasilan.name).write_text(
                    paylasilan.read_text(encoding="utf-8"), encoding="utf-8")
            yol = Path(tmp) / f"{slug}.html.j2"
            yol.write_text(html, encoding="utf-8")
            try:
                kareler = list(render_fn(yol, UC_METINLER))
            except Exception as e:   # noqa: BLE001
                hata = f"Render sırasında hata: {e}"
                log.info(f"[arketip] tur {deneme}: {hata[:120]}")
                continue
            ok, hata = vision_kapisi(kareler, vision_call=vision_call)
            if not ok:
                log.info(f"[arketip] tur {deneme}: vision reddetti — {hata[:120]}")
                continue

        hedef = templates_dir / f"{slug}.html.j2"
        hedef.write_text(html, encoding="utf-8")
        _kayit_ekle(slug, ad)
        return TasarimSonucu(True, slug=slug, tur=deneme)

    # KAYDETMEDEN PES: 41'inci bozuk kalıbı diske yazmaktansa hiç yazmamak.
    return TasarimSonucu(False, sebep=(f"{tur} denemede kapılardan geçemedi. "
                                       f"Son sebep: {hata}"), tur=tur)


def gercek_render(*, settings, language: str = "tr", dna_css: str = ""):
    """Üretimdeki `render_fn`: her uç metin için bir kare çizer.

    fps=1 ile tek kare yeter — ilerleme çubuğu animasyonunun ilk karesi bize
    yerleşimi zaten gösteriyor. `dna_smoke` ile aynı desen; oradan farkı ÜÇ
    metinle çağrılması.
    """
    from short_bot.locale import ui_labels_for
    from short_bot.models import RenderJob
    from short_bot.renderer import render_frames

    def _f(sablon_yolu: Path, metinler: Sequence) -> list[Path]:
        etiketler = ui_labels_for(language)
        kareler: list[Path] = []
        kok = Path(sablon_yolu).parent
        for i, script in enumerate(metinler):
            job = RenderJob(
                script=script, bg_image_path=None,
                music_path=Path("dummy.mp3"),   # render_frames okumaz
                channel_colors={"primary": "#d0021b", "accent": "#ffe600",
                                "bg_gradient": ["#3a3a3a", "#141414"]},
                handle="@onizleme", duration_s=6, language=language)
            hedef = kok / f"kare{i}"
            render_frames(job, Path(sablon_yolu), hedef, fps=1,
                          browser=getattr(settings, "playwright_browser", "chromium"),
                          ui_labels=etiketler, dna_css=dna_css)
            pngs = sorted(hedef.glob("*.png"))
            if pngs:
                kareler.append(pngs[len(pngs) // 2])
        return kareler
    return _f


def gercek_vision(*, settings, secrets):
    """Üretimdeki `vision_call`. Modele ulaşılamazsa None döner → FAIL-CLOSED.

    `footage_matcher._judge_image_file` deseni: yerel PNG `image_path` ile
    gönderilir, prompt'a @yol konmaz.
    """
    from short_bot.archetype_gate import VISION_SORUSU
    from short_bot.config import resolve_ai_call

    try:
        cagri = resolve_ai_call(settings, secrets, "vision")
    except Exception:   # noqa: BLE001 — vision yapılandırılmamış
        return None

    def _f(yol: Path) -> dict:
        from short_bot.claude_cli import _extract_json, _invoke_raw
        ham = _invoke_raw(VISION_SORUSU, backend=cagri.backend,
                          model=cagri.model, claude_path=cagri.claude_path,
                          api_key=cagri.api_key, timeout_s=90, image_path=Path(yol))
        return json.loads(_extract_json(ham))
    return _f


def _kayit_ekle(slug: str, ad: str) -> None:
    """`config/archetypes.json`'a giriş ekler — panel açılırında görünsün.

    Kayıt yazılamazsa şablon yine de kullanılabilir (ARCHETYPES listesi JSON'u
    okuyamazsa boş listeye düşüyor ve sabit dördü kalıyor); bu yüzden hata
    üretimi durdurmaz, uyarı olarak geçer.
    """
    p = Path("config/archetypes.json")
    try:
        kayit = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        if any(a.get("slug") == slug for a in kayit):
            return
        kayit.append({"slug": slug, "label": ad,
                      "subtitle": "Claude tarafından tasarlandı",
                      "pexels_queries": [], "defaults": {}})
        p.write_text(json.dumps(kayit, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except Exception as e:   # noqa: BLE001
        log.warning(f"[arketip] archetypes.json güncellenemedi: {e}")
