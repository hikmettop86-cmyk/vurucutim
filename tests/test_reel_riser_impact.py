"""RISER → IMPACT grameri: reveal'den önce yükselen ses, tam reveal karesinde vuruş.

NEDEN: riser bir TAHMİN MAKİNESİDİR. Beyne "bir şey geliyor" der ve bu, kaydırma
dürtüsünü bastırır — çözülmeden gidemezsin. Impact sonra tahmini ÖDÜLLENDİRİR.
Kısa formattaki en güvenilir "kaydırma önleyici" bu; ve otomatik boru hatlarının
neredeyse hiçbiri yapmıyor.

TEKNİK: riser'ın TEPESİ tam reveal karesine denk gelmeli. Riser'lar sonda doruğa
çıkar → dosyayı, BİTİŞİ reveal anına gelecek şekilde geciktir. SFX gibi 1.5sn'ye
KIRPILMAZ (kırpılırsa yükseliş yok olur, sadece bir uğultu kalır).
"""
import subprocess
from pathlib import Path

from short_bot import reel_assembler
from short_bot.assets_library import MAX_RISER_S, RISER_CATEGORY


def _graph(tmp_path, monkeypatch, **over):
    clips = [tmp_path / "c0.mp4"]; clips[0].write_bytes(b"x")
    narration = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    cmds = []
    monkeypatch.setattr(reel_assembler, "_run",
                        lambda cmd: (cmds.append(list(cmd)),
                                     subprocess.CompletedProcess(cmd, 0, "", ""))[1])
    kw = dict(clip_paths=clips, seg_spans=[(0.0, 30.0)], frames_dir=tmp_path / "f",
              narration_path=narration, music_path=None,
              out_path=tmp_path / "out.mp4", cut_times=[], duration_s=30.0, zoom=False)
    kw.update(over)
    reel_assembler.assemble_reel(**kw)
    final = next(c for c in cmds if "-filter_complex" in c)
    return final[final.index("-filter_complex") + 1]


def test_riser_ends_exactly_on_the_reveal(tmp_path, monkeypatch):
    """Riser'ın TEPESİ reveal karesine denk gelmeli → BİTİŞİ oraya hizalanır."""
    riser = tmp_path / "r.mp3"; riser.write_bytes(b"r")
    fc = _graph(tmp_path, monkeypatch, riser=(riser, 2.0), reveal_s=20.0)
    # riser 2sn → 18.0sn'de başlamalı ki 20.0'da doruğa çıksın
    assert "adelay=18000|18000" in fc, f"riser reveal'e hizalanmadı: {fc}"


def test_impact_lands_on_the_reveal_frame(tmp_path, monkeypatch):
    impact = tmp_path / "i.mp3"; impact.write_bytes(b"i")
    fc = _graph(tmp_path, monkeypatch, impact=impact, reveal_s=20.0)
    assert "adelay=20000|20000" in fc


def test_riser_is_not_trimmed_like_an_sfx():
    """SFX 1.5sn'ye kırpılır; riser KIRPILIRSA yükseliş yok olur."""
    from short_bot.assets_library import MAX_SFX_S
    assert MAX_RISER_S > MAX_SFX_S
    assert MAX_RISER_S >= 2.0


def test_riser_is_its_own_category_not_an_sfx():
    """Riser SFX havuzuna KARIŞMAMALI — kesim başına çalarsa video uğultuya döner."""
    from short_bot.assets_library import SFX_CATEGORIES
    assert RISER_CATEGORY not in SFX_CATEGORIES


def test_no_reveal_means_no_riser_or_impact(tmp_path, monkeypatch):
    """Tepe bilinmiyorsa gramer kurulmaz (bozuk filtre grafiği olmasın)."""
    riser = tmp_path / "r.mp3"; riser.write_bytes(b"r")
    fc = _graph(tmp_path, monkeypatch, riser=(riser, 2.0), reveal_s=None)
    assert "adelay=18000" not in fc


def test_riser_before_the_video_start_is_clamped(tmp_path, monkeypatch):
    """Reveal çok erkense riser negatif gecikmeye kaçmamalı."""
    riser = tmp_path / "r.mp3"; riser.write_bytes(b"r")
    fc = _graph(tmp_path, monkeypatch, riser=(riser, 3.0), reveal_s=1.0)
    assert "adelay=-" not in fc
    assert "adelay=0|0" in fc
