"""ÖNİZLEME = GERÇEK ÇIKTI.

KULLANICI KURALI (2026-08-21): "kullanıcı ne oluşturduğunu görmeli, şablonlar
aynı olmalı" — panelde görülen kare, kanalın gerçekten üreteceği kareyle
birebir aynı olmalı.

ÖLÇÜLDÜ: `gercek_render` SABİT kırmızı/sarı palet ve BOŞ `dna_css` ile
çiziyordu (`channel_colors={"primary": "#d0021b", "accent": "#ffe600"}`,
`handle="@onizleme"`). Yani kapılar şablonu kanalın paletiyle DEĞİL, jenerik
bir paletle yargılıyordu; kanal sonra kendi DNA'sıyla bambaşka render ediyordu.
"""
from __future__ import annotations

from pathlib import Path


def _yakala(monkeypatch):
    gorulen = {}

    def _sahte(job, sablon, hedef, **kw):
        gorulen.setdefault("cagri", []).append(
            {"colors": job.channel_colors, "handle": job.handle,
             "language": job.language, "duration_s": job.duration_s,
             "dna_css": kw.get("dna_css", "")})
        Path(hedef).mkdir(parents=True, exist_ok=True)
        (Path(hedef) / "k000.png").write_bytes(b"x")
        return 1
    monkeypatch.setattr("short_bot.renderer.render_frames", _sahte)
    return gorulen


def test_render_KANALIN_PALETINI_kullanir(monkeypatch, tmp_path):
    from short_bot.archetype_design import gercek_render
    from short_bot.archetype_gate import UC_METINLER
    g = _yakala(monkeypatch)
    r = gercek_render(settings=None, language="de",
                      colors={"primary": "#800020", "accent": "#0047ab",
                              "bg_gradient": ["#111", "#000"]},
                      handle="@trabzonspor", dna_css="/* dna */")
    r(tmp_path / "x.html.j2", UC_METINLER[:1])
    c = g["cagri"][0]
    assert c["colors"]["primary"] == "#800020", "sabit palet hâlâ kullanılıyor"
    assert c["colors"]["accent"] == "#0047ab"
    assert c["handle"] == "@trabzonspor"
    assert c["language"] == "de"
    assert c["dna_css"] == "/* dna */"


def test_palet_VERILMEZSE_ayirt_edilebilir_varsayilan(monkeypatch, tmp_path):
    """Varsayılan kalabilir ama kanal paleti verildiğinde EZİLMEMELİ."""
    from short_bot.archetype_design import gercek_render
    from short_bot.archetype_gate import UC_METINLER
    g = _yakala(monkeypatch)
    gercek_render(settings=None)(tmp_path / "x.html.j2", UC_METINLER[:1])
    assert g["cagri"][0]["colors"]["primary"].startswith("#")


def test_arketip_isi_KANALIN_DNASINI_gecirir(monkeypatch, tmp_path):
    """İş, kanalın gerçek paletini/handle'ını/dilini render'a taşımalı."""
    from short_bot.archetype_design import TasarimSonucu
    import short_bot.web.routes.channel_chat as CH

    gorulen = {}
    monkeypatch.setattr(CH, "gercek_render",
                        lambda **kw: (gorulen.update(kw), (lambda *a: []))[1])
    monkeypatch.setattr(CH, "gercek_vision", lambda **kw: None)
    monkeypatch.setattr(CH, "adaylar_uret",
                        lambda niyet, **kw: [TasarimSonucu(False, sebep="x")])

    from short_bot.config import ChannelConfig, save_channel
    d = tmp_path / "channels"
    d.mkdir()
    save_channel(d / "tk.yaml", ChannelConfig(
        slug="tk", name="TK", keywords=["a"], rss_locale="",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="stadium",
        colors={"primary": "#800020", "accent": "#0047ab",
                "bg_gradient": ["#4a0012", "#0d0d0d"]},
        handle="@tk", output_dir="out", enabled=False, language="tr"))

    monkeypatch.setattr(CH, "_tasarim_llm", lambda a, b: (lambda p: ""))
    CH._arketip_isi("j", niyet="x", ad="TK", slug="tk", channels_dir=d,
                    templates_dir=tmp_path, settings=None, secrets={})
    assert gorulen.get("colors", {}).get("primary") == "#800020"
    assert gorulen.get("handle") == "@tk"
    assert gorulen.get("language") == "tr"
