"""YouTube düğmeleri var olan bir forma bağlanmalı.

CANLI VAKA (2026-08-22, kullanıcı bildirimi + ekran görüntüsü): Japonca kanalın
düzenleme sayfasında client_secrets.json seçiliyor, "↑ Yükle" tıklanıyor ve
HİÇBİR ŞEY OLMUYOR.

Sebep: ortak parça (_partials/core/youtube.html.j2) düğmeleri HTML5
`form="yt-upload-secrets-form"` ile ana formun DIŞINDAKİ gizli formlara
bağlıyor (iç içe form yasak). O gizli formlar sayfada TANIMLI DEĞİLSE düğme
var olmayan bir forma işaret eder ve sessizce ölür — hata yok, log yok.

Durum: kart sayfası formları satır içi tanımlamış, kürate sayfası ortak parçayı
dahil etmiş, YORUM sayfası İKİSİNİ DE yapmamıştı.
"""
from __future__ import annotations

from pathlib import Path

import pytest

KOK = Path("src/short_bot/web/templates")
GEREKLI = ("yt-upload-secrets-form", "yt-connect-form", "yt-disconnect-form")

# Ortak YouTube parçasını içeren HER sayfa formları da sağlamalı.
SAYFALAR = ["channels/edit.html.j2", "channels/edit_yorum.html.j2",
            "channels/edit_curated.html.j2"]


def _sayfa_metni(ad: str) -> str:
    """Sayfa + dahil ettiği parçaların metni (tek kademe include yeter)."""
    s = (KOK / ad).read_text(encoding="utf-8")
    for parca in ("_partials/youtube_hidden_forms.html.j2",
                  "_partials/core/youtube.html.j2"):
        if parca in s:
            s += (KOK / parca).read_text(encoding="utf-8")
    return s


@pytest.mark.parametrize("sayfa", SAYFALAR)
def test_youtube_dugmeleri_var_olan_forma_baglanir(sayfa):
    metin = _sayfa_metni(sayfa)
    if "core/youtube.html.j2" not in metin and "yt-upload-secrets-form" not in metin:
        pytest.skip(f"{sayfa}: YouTube bloğu yok")
    for form_id in GEREKLI:
        assert f'id="{form_id}"' in metin, (
            f"{sayfa}: '{form_id}' formu TANIMLI DEĞİL — düğme sessizce ölür")


@pytest.mark.parametrize("sayfa", SAYFALAR)
def test_form_action_lari_gercek_rotalara_gider(sayfa):
    metin = _sayfa_metni(sayfa)
    if "yt-upload-secrets-form" not in metin:
        pytest.skip(f"{sayfa}: YouTube bloğu yok")
    for yol in ("youtube/upload-secrets", "youtube/connect", "youtube/disconnect"):
        assert yol in metin, f"{sayfa}: {yol} action'ı yok"


def test_dosya_yukleme_formu_multipart():
    """enctype olmadan dosya gitmez — sessiz başarısızlık."""
    metin = (KOK / "_partials/youtube_hidden_forms.html.j2").read_text(encoding="utf-8")
    i = metin.index("yt-upload-secrets-form")
    assert "multipart/form-data" in metin[i:i + 300]


# --- şablon sözleşmesi ---------------------------------------------------------

def test_her_rota_ortak_parcanin_istedigi_baglami_veriyor():
    """CANLI VAKA (2026-08-22): yorum rotası `yt_has_secrets`'i HİÇ hesaplamıyordu.
    Jinja'da tanımsız değişken FALSY'dir — sayfa client_secrets yüklendikten
    sonra bile hep "yükle" ekranında kalıyor, "Bağla" düğmesi asla görünmüyordu.
    Hata yok, log yok: sessizce kapalı bir özellik.

    Ortak parçanın istediği bağlam parçanın başında yazılı; her tüketici rota
    hepsini vermek ZORUNDA."""
    import re
    parca = (KOK / "_partials/core/youtube.html.j2").read_text(encoding="utf-8")
    # Parçanın kendi belgelediği sözleşme
    gerekli = {"yt_connected", "yt_info", "yt_has_secrets", "yt_secrets_abs",
               "linkable", "yt_clash", "creds_slug"}
    assert gerekli <= set(re.findall(r"\b\w+\b", parca)), "parça sözleşmesi değişmiş"

    from pathlib import Path as P
    rotalar = {
        "channel_edit": P("src/short_bot/web/routes/channel_edit.py"),
        "yorum": P("src/short_bot/web/routes/yorum.py"),
        "curated": P("src/short_bot/web/routes/curated.py"),
    }
    for ad, yol in rotalar.items():
        if not yol.exists():
            continue
        s = yol.read_text(encoding="utf-8")
        if "core/youtube" not in s and "edit" not in s:
            continue
        eksik = [g for g in sorted(gerekli) if f"{g}=" not in s]
        assert not eksik, f"{ad} rotası şu bağlamı vermiyor: {eksik}"
