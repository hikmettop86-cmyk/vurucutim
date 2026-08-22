"""Marka güvenliği süzgeci — YouTube'da neredeyse kesin para kazandırmayan konular.

NEDEN AYRI BİR SÜZGEÇ: dikey kapısı konunun kanalın işi olup olmadığını sorar,
AI kapısı olay var mı diye sorar. İkisi de "bu videoya reklam verilir mi" diye
SORMAZ. Magazin dikeyinde canlı havuzdan 「ブラジャーをあえて見せる」ファッション
çıktı ve kapıyı 7,0 ile geçti (2026-08-22 ölçümü).

KRİTİK AYRIM (bu modülün tasarımını belirleyen şey): `adalet` dikeyinde şiddet
ve ölüm İÇERİĞİN KENDİSİDİR. Hepsini elemek dikeyi öldürür — DE havuzunda 31
adayın çoğu suç haberi. YouTube'un kuralı da öyle değil: sıradan suç haberi
(gözaltı, dava, kaza, kayıp kişi) sınırlı reklamla yayınlanır, GRAFİK DETAY
yayınlanmaz.

Bu yüzden liste DAR ve kategorilere ayrılmış: yalnız neredeyse kesin
demonetize olan sınıflar. Sıradan suç haberi ELENMEZ.

SEVİYELER
  "off"    — süzgeç yok (eski davranış)
  "normal" — yalnız kesin sınıflar (varsayılan)
  "strict" — sınırdakiler de (beden odaklı magazin dili, linç/ifşa)

ARZ HESABI: bu süzgeci agresif tutmak UCUZ, çünkü dikey arzı bol (magazin
32-48/gün, eşik 4). Olgu kapısının tersi: orada yanlış pozitif üretimi
durduruyordu, burada yalnız bir adayı düşürüyor.
"""
from __future__ import annotations

import re

from short_bot.text_normalize import locale_fold

LEVELS = ("off", "normal", "strict")

# Kategori -> dil -> kalıplar. Kalıplar locale_fold edilmiş metinde aranır.
#
# Her kalıp CANLI HAVUZDAN ya da YouTube'un reklamveren dostu içerik
# kurallarının açık maddelerinden geliyor; tahminle eklenmiş yok.
_NORMAL: dict[str, dict[str, tuple[str, ...]]] = {
    # Cinsel/müstehcen — YouTube'da en net demonetize sınıfı.
    "cinsel": {
        "ja": ("ブラジャー", "下着", "ランジェリー", "ヌード", "全裸", "性的",
               "猥褻", "わいせつ", "強要疑惑", "セクハラ", "エロ"),
        "de": ("dessous", "unterwäsche", "nacktfoto", "oben ohne", "sexuell",
               "vergewaltig", "missbrauch", "prostitution", "porno"),
        "tr": ("iç çamaşır", "çıplak", "müstehcen", "taciz", "tecavüz",
               "cinsel istismar", "fuhuş", "porno"),
        "en": ("lingerie", "underwear", "nude", "topless", "sexual assault",
               "rape", "molest", "prostitution", "porn"),
        "es": ("lencería", "desnud", "abuso sexual", "violación", "prostitución"),
        "fr": ("lingerie", "nue", "agression sexuelle", "viol", "prostitution"),
    },
    # Grafik ceset/uzuv detayı — sıradan ölüm haberi DEĞİL, detayın kendisi.
    "grafik": {
        "ja": ("遺体の一部", "バラバラ遺体", "腐乱", "切断された", "首を切",
               "惨殺", "むごたらしい"),
        "de": ("verwest", "enthauptet", "zerstückelt", "verstümmelt",
               "leichenteile", "grausig"),
        "tr": ("parçalanmış ceset", "cesedi parçalan", "başı kesil", "kafası kesil",
               "çürümüş ceset", "vahşice"),
        "en": ("decomposed body", "dismembered", "beheaded", "mutilated",
               "body parts"),
        "es": ("descuartizad", "decapitad", "cuerpo en descomposición"),
        "fr": ("décapité", "démembré", "corps en décomposition"),
    },
    "intihar": {
        "ja": ("自殺", "自死", "飛び降り"),
        "de": ("selbstmord", "suizid", "selbsttötung"),
        "tr": ("intihar", "kendini as"),
        "en": ("suicide", "took his own life", "took her own life"),
        "es": ("suicidio",),
        "fr": ("suicide",),
    },
    "cocuk": {
        "ja": ("児童ポルノ", "児童買春", "幼児虐待", "child abuse"),
        "de": ("kindesmissbrauch", "kinderpornografie", "kindesmisshandlung"),
        "tr": ("çocuk istismarı", "çocuk pornografisi", "çocuğa tacir"),
        "en": ("child abuse", "child porn", "child exploitation"),
        "es": ("abuso infantil", "pornografía infantil"),
        "fr": ("pédopornographie", "maltraitance d'enfant"),
    },
    "idam": {
        "ja": ("死刑執行", "処刑"),
        "de": ("hinrichtung", "richtet.*hin", "todesstrafe vollstreckt"),
        "tr": ("idam edildi", "infaz edildi"),
        "en": ("executed by", "execution carried out"),
        "es": ("ejecutado por",),
        "fr": ("exécuté par",),
    },
    "hayvan": {
        "ja": ("動物虐待", "虐待され", "殺処分"),
        "de": ("tierquälerei", "tier misshandelt"),
        "tr": ("hayvana işkence", "hayvan katliamı"),
        "en": ("animal cruelty", "animal abuse"),
        "es": ("maltrato animal",),
        "fr": ("maltraitance animale",),
    },
    "uyusturucu": {
        "ja": ("覚醒剤", "大麻", "コカイン", "薬物"),
        "de": ("kokain", "heroin", "crystal meth", "drogenbesitz"),
        "tr": ("uyuşturucu", "kokain", "eroin", "esrar"),
        "en": ("cocaine", "heroin", "meth", "drug possession"),
        "es": ("cocaína", "heroína", "narcotráfico"),
        "fr": ("cocaïne", "héroïne", "stupéfiants"),
    },
}

# SINIRDAKİLER — "strict" seviyede eklenir. Bunlar tek başına demonetize
# etmez ama kanalın tonunu aşağı çeker: beden odaklı magazin dili, linç/ifşa.
_STRICT: dict[str, dict[str, tuple[str, ...]]] = {
    "beden": {
        "ja": ("超ミニ", "ミニスカ", "谷間", "美脚", "水着姿", "スタイル抜群",
               "細すぎ", "ヘソ出"),
        "de": ("bikini", "dekolleté", "hotpants"),
        "tr": ("bikini", "dekolte", "mini etek"),
        "en": ("bikini", "cleavage", "miniskirt"),
        "es": ("bikini", "escote"),
        "fr": ("bikini", "décolleté"),
    },
    "linc": {
        "ja": ("炎上", "晒され", "叩かれ", "ドン引き"),
        "de": ("shitstorm", "pranger"),
        "tr": ("linç", "ifşa oldu", "topa tutuldu"),
        "en": ("backlash storm", "cancelled online"),
        "es": ("linchamiento digital",),
        "fr": ("lynchage",),
    },
}


def _tara(metin: str, tablo: dict[str, dict[str, tuple[str, ...]]],
          dil: str) -> str | None:
    for kategori, diller in tablo.items():
        for kalip in diller.get(dil, ()):
            # Kalıplar düz metin; yalnız regex meta taşıyanlar desen olarak aranır.
            if any(ch in kalip for ch in ".*+?[]()"):
                if re.search(kalip, metin):
                    return kategori
            elif locale_fold(kalip) in metin:
                return kategori
    return None


def risk_of(title: str, body: str = "", *, language: str = "tr",
            level: str = "normal") -> str | None:
    """Bu haber marka güvenliği açısından riskli mi? Riskliyse KATEGORİ döner.

    ``level`` geçersizse SESSİZCE geçmez — yazım hatası yüzünden kapalı çalışan
    bir süzgeç en kötüsüdür (bkz. config._trends_intent'teki aynı gerekçe).
    """
    if level not in LEVELS:
        raise ValueError(
            f"brand_safety seviyesi {level!r} geçersiz — {', '.join(LEVELS)} olmalı")
    if level == "off":
        return None
    dil = (language or "").split("-")[0].lower()
    metin = locale_fold(f"{title or ''} {body or ''}")
    if not metin.strip():
        return None
    bulunan = _tara(metin, _NORMAL, dil)
    if bulunan:
        return bulunan
    if level == "strict":
        return _tara(metin, _STRICT, dil)
    return None
