"""MERAK MİMARİSİ: 3 aday senaryo -> rubrik yargıcı -> doktor turu.

Kullanıcı teşhisi (2026-07-16): videolar komik ama SÜRÜKLEYİCİ değil — hook
durdurmuyor, beat'ler arası 'sonra ne olacak?' çekişi yok, tepe 'vay be'
dedirtmiyor. Tek taslağı cilalamak sıkıcı taslağı cilalamaya mahkûm; ÇEŞİTLİLİK
+ SEÇİM iterasyonu yener: her adaya farklı merak iskeleti dayatılır, rubrik
tabanlı yargıç kazananı seçer, doktor yalnız somut şikâyetleri düzeltir.

Rubrik kaynağı: DiscoverNow mizah DNA analizi (manuel araştırma tarihçesi,
bkz. discovernow-mizah-dna) + anlatı ilk-ilkeleri (bilgi-boşluğu kuramı:
merak = izleyicinin bildiği ile bilmek istediği arasındaki açık; açık erken
kapanırsa izleme sebebi biter). Transkript tabanlı doğrulama DENENDİ
(2026-07-16, YouTube Data API) — kota dolu olduğu için eklenemedi; kota
açılınca rubrik gerçek transkript analiziyle zenginleştirilebilir.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# Her adaya BİR iskelet dayatılır — üç aday üç farklı merak stratejisi dener.
# (persona/çeşitleme reçetesi korunur; iskelet ÜSTÜNE biner.)
CURIOSITY_SKELETONS: list[tuple[str, str]] = [
    ("GİZEM-ÖNCE",
     "Hook somut ve spesifik bir SORU/GİZEM açar ('Bu balık neden herkesi "
     "korkutuyor?' gibi jenerik değil — 'Şu masum surat var ya, az sonra "
     "yapacağı şeye inanamayacaksın' tadında, SAHNEYE bağlı). Cevabı EN SONA "
     "SAKLA: her beat cevaba bir adım yaklaştırır ama YENİ bir mini-soru da "
     "açar. Cevap reveal beat'inden önce ASLA sızmaz."),
    ("TIRMANAN BAHİS",
     "Her beat bir öncekinden DAHA BÜYÜK bir iddia/tehlike/absürtlük kurar — "
     "'bu daha bir şey değil...' merdiveni. İzleyici her basamakta 'bundan "
     "büyüğü olamaz' der, sen bir üstünü koyarsın. Tepe = en büyük basamak; "
     "erken zirve YASAK (sonrası düşüş hissi verir)."),
    ("SAHTE ÇÖZÜM + TWIST",
     "İzleyiciye cevabı aldığını HİSSETTİR (bir beat sahte-çözüm gibi kapanır), "
     "sonra tepe onu TERS KÖŞE yapar — gerçek asıl o an açığa çıkar. Sahte "
     "çözüm inandırıcı olmalı; twist kliplerde GERÇEKTEN görünen bir şeyden "
     "doğmalı, uydurma olay YASAK."),
]

# Yargıcın puanlama rubriği. Kaynak: DiscoverNow DNA + anlatı ilk-ilkeleri.
RUBRIC = """PUANLAMA RUBRİĞİ (her aday için her maddeye 0-10):
1. AÇIK DÖNGÜ: hook somut/spesifik bir soru-gizem açıyor mu (jenerik 'bakın ne
   olacak' = 2 puan altı)? Cevap reveal beat'inden önce SIZINTI yapıyor mu?
   (sızıntı varsa bu madde en fazla 3)
2. BEAT-SONU KANCASI: her beat'in SON cümlesi sonraki beat'i merak ettiriyor mu
   (yeni mini-soru, tehdit, iddia)? Merakı SIFIRLAYAN (kapanan) beat sayısı
   kadar puan kır.
3. TIRMANIŞ: beat'ler yükseliyor mu — her biri öncekinden daha büyük
   iddia/tehlike/absürtlük? Düz sıralama (beat'ler yer değiştirse fark etmez)
   = 4 altı.
4. ÖDEME: tepe, hook'un açtığı soruyu GERÇEKTEN cevaplıyor mu ve cevap
   beklenenden İYİ mi (ters köşe/abartı)? Vaat ödenmiyorsa aday DİSKALİFİYE.
5. MİZAH YOĞUNLUĞU: benzetme/replik/patlama-cümle sıklığı; boş geçiş cümlesi
   ('bak şimdi', 'işin sırrı') başına puan kır.
6. GÖRÜNTÜ SADAKATİ: her beat kendi klibinin TARİFİNDE olan şeyi mi anlatıyor?
   Tarif dışı somut olay uyduran aday DİSKALİFİYE.
7. KLİŞE: yasak açılışlar ('Ula', 'bak hele', 'biliyor muydunuz') ya da
   birbirinin aynısı kalıplar varsa puan kır."""
