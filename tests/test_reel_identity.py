"""Feed kimliği kilidi: kanal feed'de TANINSIN — ama video taze kalsın.

Bu modülün bütün mesele si iki ilkeyi ÇELİŞTİRMEDEN bir arada tutmak:
  • tanınma   → font/renk/yerleşim/ses/sting/rozet HER bölümde AYNI
  • tazelik   → efekt/SFX/marker/müzik/tempo bölümden bölüme DEĞİŞİR

O yüzden testler yalnız "kilitlendi mi" demiyor; kilidin çeşitliliği ÖLDÜRMEDİĞİNİ
de ölçüyor. Yanlış sütunu kilitlemek, düzeltmeye çalıştığımız sorunu geri getirir.
"""
from short_bot.config import ReelConfig
from short_bot.reel_identity import (LOCKED_FIELDS, VARYING_FIELDS, lock_profile,
                                     locked_accent, locked_layout, pick_sting)
from short_bot.reel_variation import build_variation_profile


class _Ch:
    slug = "bilinmeyen-tarih"
    language = "tr"
    handle = "@bt"
    colors = {"primary": "#0ea5e9", "accent": "#facc15", "bg_gradient": ["#0f172a", "#020617"]}
    reel = ReelConfig(enabled=True, voice_id="v1", highlight_color="#ffd400",
                      layout="auto", accent_vary=True)


class _Ch2(_Ch):
    slug = "baska-kanal"


def _kilitli(seed):
    return lock_profile(build_variation_profile(_Ch(), seed), _Ch())


def test_kilitsiz_haliyle_AKSAN_her_videoda_DEGISIYOR():
    """Düzeltilen sorunun kendisini ölçüyoruz — gerekçe kayıt altında.

    accent_vary=True her videoda aksan rengini döndürüyor. Yüzü olmayan bir kanalda
    bu, kimliğin kendisini silmek demek: aynı kanalın iki videosu feed'de birbirine
    benzemiyor.
    """
    renkler = {build_variation_profile(_Ch(), s).accent for s in range(12)}
    yerlesim = {build_variation_profile(_Ch(), s).layout for s in range(12)}
    assert len(renkler) > 1 or len(yerlesim) > 1, (
        "varyasyon motoru artık dönmüyorsa bu kilidin gerekçesi çürür")


def test_kilit_aksan_ve_yerlesimi_SABITLER():
    renkler = {_kilitli(s).accent for s in range(20)}
    yerlesim = {_kilitli(s).layout for s in range(20)}
    assert len(renkler) == 1, f"aksan hâlâ dönüyor: {renkler}"
    assert len(yerlesim) == 1, f"yerleşim hâlâ dönüyor: {yerlesim}"


def test_kilit_CESITLILIGI_OLDURMEZ():
    """En önemli test: yanlış sütunu kilitlersek otomasyon parmak izi geri gelir.

    İzleyici kanalı kesme efektinden ya da SFX'ten TANIMAZ. Onlar dönmeye devam
    etmeli — kilidin amacı çeşitliliği yok etmek değil, çeşitliliği izleyicinin
    tanımak için KULLANMADIĞI alanlara taşımak.
    """
    profiller = [_kilitli(s) for s in range(24)]
    assert len({p.cut_effect for p in profiller}) > 1, "kesme efekti dönmüyor"
    assert len({p.marker_kit for p in profiller}) > 1, "belirteç seti dönmüyor"
    assert len({p.cut_pacing for p in profiller}) > 1, "kesim temposu dönmüyor"
    assert len({p.hook_angle for p in profiller}) > 1, "açılış açısı dönmüyor"


def test_kilitli_ve_donen_alanlar_ORTUSMEZ():
    assert not (set(LOCKED_FIELDS) & set(VARYING_FIELDS))


def test_aksan_kanalin_kendi_renginden_gelir():
    assert locked_accent(_Ch()).lower().startswith("#")
    # Aynı kanal → hep aynı renk
    assert locked_accent(_Ch()) == locked_accent(_Ch())


def test_acik_layout_ayari_kilidi_de_belirler():
    """Kullanıcı sözü son sözdür: layout='classic' dendiyse kilit onu kullanır."""
    class _C(_Ch):
        reel = ReelConfig(enabled=True, voice_id="v1", layout="lower_left")
    assert locked_layout(_C()) == "lower_left"


def test_auto_layout_KANALA_gore_sabitlenir_seed_e_gore_degil():
    # Aynı kanal → hep aynı; farklı kanal → farklı olabilir (ama kendi içinde sabit)
    assert locked_layout(_Ch()) == locked_layout(_Ch())
    assert locked_layout(_Ch2()) == locked_layout(_Ch2())


# --- STING ----------------------------------------------------------------

def test_sting_her_bolumde_AYNI_dosya(tmp_path):
    """İmza ancak TEKRARLANINCA imza olur. Seed'e göre seçilseydi imza olmazdı."""
    for i in range(5):
        (tmp_path / f"s{i}.mp3").write_bytes(b"x")
    secimler = {pick_sting(tmp_path, "bilinmeyen-tarih") for _ in range(10)}
    assert len(secimler) == 1


def test_farkli_kanal_farkli_sting_alabilir(tmp_path):
    for i in range(8):
        (tmp_path / f"s{i}.mp3").write_bytes(b"x")
    a = pick_sting(tmp_path, "kanal-a")
    b = pick_sting(tmp_path, "kanal-b")
    assert a is not None and b is not None
    # Aynı dosyaya düşmeleri mümkün (hash), ama her biri kendi içinde sabit olmalı
    assert pick_sting(tmp_path, "kanal-a") == a
    assert pick_sting(tmp_path, "kanal-b") == b


def test_sting_yoksa_none(tmp_path):
    assert pick_sting(tmp_path, "x") is None
    assert pick_sting(tmp_path / "yok", "x") is None
