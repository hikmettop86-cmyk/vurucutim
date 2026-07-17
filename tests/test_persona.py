"""Reel anlatım personası: yükleme + prompt bloğu."""
import pytest


def test_bos_slug_none():
    from short_bot.persona import load_persona
    assert load_persona("", language="tr") is None


def test_vahsi_mizah_yuklenir():
    from short_bot.persona import load_persona
    p = load_persona("vahsi_mizah", language="tr")
    assert p is not None
    assert p.slug == "vahsi_mizah"
    assert "Aşık Kargayi" in p.few_shot   # ozan imzası — marka öğesi
    assert len(p.rules) >= 5
    assert p.humor_check is True


def test_bilinmeyen_slug_raise():
    from short_bot.persona import load_persona
    with pytest.raises(RuntimeError, match="persona"):
        load_persona("boyle_bir_persona_yok", language="tr")


def test_yanlis_dilde_raise():
    # Türk dizisi referansları yalnız tr'de. Almanca'da vahsi_mizah RuntimeError.
    from short_bot.persona import load_persona
    with pytest.raises(RuntimeError, match="persona"):
        load_persona("vahsi_mizah", language="de")


def test_persona_block_few_shot_ve_kurallari_icerir():
    from short_bot.persona import load_persona, persona_block
    p = load_persona("vahsi_mizah", language="tr")
    blok = persona_block(p)
    assert "Aşık Kargayi" in blok            # few-shot örneği
    assert "BÜRÜNDÜR" in blok                # kurallar
    assert "GERÇEK" in blok


def test_signature_style_seed_ile_doner():
    # Kapanış STİLİ DÖNER (formülleşme kırılır). OZAN KALDIRILDI → hepsi kafiyesiz.
    from short_bot.persona import signature_style, SIGNATURE_STYLES
    n = len(SIGNATURE_STYLES)
    assert n == 4                                     # 4 kafiyesiz güldüren stil
    etiketler = {signature_style(s)[0] for s in range(n)}
    assert len(etiketler) == n                        # hepsi FARKLI
    assert signature_style(n) == signature_style(0)   # döngüsel (deterministik)
    assert all("OZAN" not in e for e, _ in SIGNATURE_STYLES)   # ozan yok


def test_persona_block_imza_stili_seed_ile_degisir():
    from short_bot.persona import load_persona, persona_block, signature_style, SIGNATURE_STYLES
    p = load_persona("vahsi_mizah", language="tr")
    n = len(SIGNATURE_STYLES)
    # Seçilen stilin etiketi bloğa GERÇEKTEN enjekte edilmeli (stil dönüyor)
    for seed in range(n):
        assert signature_style(seed)[0] in persona_block(p, seed=seed)
    # Ozan kaldırıldı: blok her seed'de ozan/beyit yazmayı YASAKLAR
    assert "ozan beyti YAZMA" in persona_block(p, seed=0)


# --- SENARYO ÇEŞİTLEME EKSENLERİ (kullanıcı: 'senaryo hep aynı kalıp') --------
# Kök: prompt açılış örneği olarak birebir 'Ula bak hele sahneye' veriyordu ve
# iskelet sabitti → her video aynı açılış + aynı ses + aynı benzetme dünyaları
# (emlakçı/kahvehane). İmza rotasyonu deseni üç bağımsız eksene genişletildi.

def test_hook_style_seed_ile_doner_ve_deterministik():
    from short_bot.persona import HOOK_STYLES, hook_style
    assert len(HOOK_STYLES) >= 5                       # gerçek çeşitlilik
    assert hook_style(7) == hook_style(7)              # deterministik
    etiketler = {hook_style(s)[0] for s in range(24)}
    assert len(etiketler) == len(HOOK_STYLES)          # hepsi sırası gelince çıkıyor


def test_frame_style_seed_ile_doner():
    from short_bot.persona import FRAME_STYLES, frame_style
    assert len(FRAME_STYLES) >= 5
    assert frame_style(3) == frame_style(3)
    assert len({frame_style(s)[0] for s in range(24)}) == len(FRAME_STYLES)


def test_metaphor_domains_iki_farkli_dunya():
    from short_bot.persona import METAPHOR_DOMAINS, metaphor_domains
    assert len(METAPHOR_DOMAINS) >= 8
    for s in range(12):
        d1, d2 = metaphor_domains(s)
        assert d1 != d2                                # aynı videoda iki FARKLI dünya
        assert d1 in METAPHOR_DOMAINS and d2 in METAPHOR_DOMAINS
    assert metaphor_domains(5) == metaphor_domains(5)  # deterministik
    # farklı videolar farklı kombinasyon görmeli (formül kırılır)
    assert len({metaphor_domains(s) for s in range(12)}) >= 6


def test_eksenler_birbirinden_bagimsiz_doner():
    # seed%N tüm eksenleri KİLİTLEMESİN: aynı imza stiline düşen iki videonun
    # açılışı/sesi farklı olabilmeli (tuzlanmış hash, reel_subscribe._idx deseni).
    from short_bot.persona import frame_style, hook_style
    ciftler = {(hook_style(s)[0], frame_style(s)[0]) for s in range(36)}
    assert len(ciftler) > max(len({hook_style(s)[0] for s in range(36)}),
                              len({frame_style(s)[0] for s in range(36)}))


def test_persona_block_cesitleme_recetesi_enjekte_edilir():
    from short_bot.persona import (frame_style, hook_style, load_persona,
                                   metaphor_domains, persona_block)
    p = load_persona("vahsi_mizah", language="tr")
    for seed in (0, 7, 13):
        blok = persona_block(p, seed=seed)
        assert "AÇILIŞ STİLİ" in blok
        assert hook_style(seed)[0] in blok
        assert "ANLATICI SESİ" in blok
        assert frame_style(seed)[0] in blok
        d1, d2 = metaphor_domains(seed)
        assert d1 in blok and d2 in blok
    # farklı seed → farklı reçete (en az bir eksen değişir)
    assert persona_block(p, seed=0) != persona_block(p, seed=7)


def test_persona_block_ula_bak_hele_kalibini_yasaklar():
    # Eski prompt bu cümleyi ÖRNEK veriyordu → model her videoda kopyaladı
    # (ölçüldü: art arda 5 videonun 5'i de 'Ula bak hele' ile açıldı).
    from short_bot.persona import load_persona, persona_block
    p = load_persona("vahsi_mizah", language="tr")
    blok = persona_block(p, seed=4)
    assert "Ula bak hele" in blok and "YASAK" in blok   # açıkça yasaklanıyor
    assert "bizimki" in blok.lower()                    # 'bizimki' dozu da sınırlı
