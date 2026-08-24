"""LLM-based interestingness scorer (0-10) per news item."""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from short_bot.claude_cli import OpenRouterError, run_json
from short_bot.models import NewsItem, ScoredItem
from short_bot.topic_taxonomy import (
    normalize_category, normalize_subject, subject_matches,
)

if TYPE_CHECKING:
    from short_bot.config import ChannelConfig


class _ItemScore(BaseModel):
    guid: str
    score: float = Field(ge=0, le=10)
    reasoning: str = Field(max_length=200)
    # Yalnız kanal canonical liste tanımladığında istenir; aksi halde boş.
    category: str = Field(default="", max_length=40)
    # Yalnız kanal saga cezasını açtığında istenir; aksi halde boş.
    subject: str = Field(default="", max_length=40)


class _ScoreResponse(BaseModel):
    scores: list[_ItemScore]


_PROMPT_TEMPLATES = {
    "tr": """Sen bir YouTube Shorts kanalının editörüsün.

KANAL: {channel_name}
KONU/ANAHTAR KELİMELER: {keywords}

Aşağıdaki haber başlıklarını bu KANALA UYGUNLUK ve ilginçlik açısından 0-10 puanla:
- 9-10: Bu kanal için son dakika çok etkileyici (kanalın konusuyla doğrudan ilgili, viral)
- 7-8: Konuyla ilgili, önemli, video yapılır
- 5-6: Konuyla yan ilgili veya derinliği zayıf
- 1-4: Sıkıcı, teknik, lokal
- 0:   KONU DIŞI (kanalın anahtar kelimeleriyle alakasız) — başlık ne kadar çekici olursa olsun 0-3 ver

MERKEZ KURALI: Kanalın öznesi haberin MERKEZİNDE olmalı; adının geçmesi yetmez.
Rakip/başka bir kulüp ya da kişi merkezli haber (ör. rakip oyuncunun maç öncesi
sözü, başka takımın kendi transferi) bu kanal için KONU DIŞIDIR → 0-3 ver.
Ölçüt: haberin gövdesi kanalın öznesi çıkarılınca ayakta kalıyorsa, konu dışıdır.

OLAY KAPISI (merkez kuralından ÖNCE uygulanır): Başlıkta anlatılacak bir OLAY
yoksa 0-3 ver — kanalın öznesi haberin tam merkezinde olsa bile.
- Olay DEĞİL: kadro/ilk onbir listesi, maç öncesi hazırlık, takımın şehre ya da
  stada varışı, antrenman izlenimi, yıldönümü / "bugün tarihte", istatistik
  derlemesi, puan durumu, maç sonrası oyuncu notları, kulübün KENDİ sitesinden
  çıkan kurumsal duyuru, yayın/program bilgisi, anket, köşe yazısı, "X kimdir".
- OLAY: gol, skor, kırmızı kart, resmi transfer, sakatlık, ayrılık, ceza, kriz,
  ilgili kişinin AĞZINDAN çıkmış söz, kulüp ya da federasyon kararı.
Ölçüt: "ne OLDU?" sorusunun cevabı başlıkta yoksa olay yoktur → 0-3.

ETKİLEŞİM EKSENİ (eşit önemdeki iki haber arasında bunu kullan):
- YUKARI çek: çatışma/karar taşıyanlar — teklif REDDİ, şart koşma, kriz, veto,
  taviz vermeme, kesinleşmiş karar, resmi açıklama, ilgili kişinin kendi sözü
- AŞAĞI çek: sonucu olmayan spekülasyon — "gündemde", "radarda", "ilgileniyor",
  "izliyor", "... mi?" türü belirsiz temaslar
Ölçüm: bu kanalda çatışma/karar çerçeveli haberler ortalamanın %43 üstünde,
belirsiz spekülasyon %12 altında performans gösterdi.

{scope_block}Başlıklar:
{listing}

SADECE şu JSON formatında yanıtla, başka metin yazma:
{{"scores": [{{"guid": "<aynısı>", "score": <0-10>, "reasoning": "<≤200 char, neden bu puan>"}}, ...]}}""",

    "en": """You are an editor for a YouTube Shorts channel.

CHANNEL: {channel_name}
TOPIC/KEYWORDS: {keywords}

Score the news headlines below from 0-10 based on RELEVANCE TO THIS CHANNEL and interestingness:
- 9-10: Major breaking news for this channel (directly on topic, viral potential)
- 7-8: On topic, important, worth a video
- 5-6: Tangentially related or shallow
- 1-4: Boring, technical, hyperlocal
- 0:   OFF-TOPIC (unrelated to channel keywords) — even if the headline sounds catchy, score 0-3

CENTER RULE: The channel's subject must be at the CENTER of the story; a passing
mention is not enough. A story centred on a rival club or another person (e.g. a
rival player's pre-match quote, another team's own transfer) is OFF-TOPIC here →
score 0-3. Test: if the story still stands after removing the channel's subject,
it is off-topic.

EVENT GATE (applied BEFORE the centre rule): if the headline carries no EVENT
to tell, score 0-3 — even when the channel's subject is dead centre.
- NOT an event: line-ups / squad lists, pre-match build-up, the team arriving in
  a city or at the stadium, training-session notes, anniversaries / "on this
  day", stat round-ups, league tables, post-match player ratings, corporate
  posts from the club's OWN website, broadcast/schedule info, polls, opinion
  columns, "who is X" profiles.
- An EVENT: a goal, a scoreline, a red card, a confirmed transfer, an injury, a
  departure, a ban, a crisis, a direct quote FROM the person involved, a club or
  federation decision.
Test: if the headline does not answer "what HAPPENED?", there is no event → 0-3.

ENGAGEMENT AXIS (use this to break ties between equally important stories):
- Score UP: conflict or decision — offer REJECTED, demands/conditions, crisis,
  veto, refusal to budge, a settled decision, official statement, a direct quote
  from the person involved
- Score DOWN: speculation with no outcome — "linked with", "on the radar",
  "interested in", "monitoring", "will he join?" style vague contact
Measured: on this channel, conflict/decision framing performed 43% above the
median while vague speculation landed 12% below.

{scope_block}Headlines:
{listing}

Reply ONLY in this JSON format, no other text:
{{"scores": [{{"guid": "<same>", "score": <0-10>, "reasoning": "<≤200 char, why this score>"}}, ...]}}""",

    "de": """Du bist Redakteur eines YouTube Shorts Kanals.

KANAL: {channel_name}
THEMA/SCHLÜSSELWÖRTER: {keywords}

Bewerte die folgenden Schlagzeilen von 0-10 nach RELEVANZ FÜR DIESEN KANAL und Interesse:
- 9-10: Wichtige Eilmeldung für diesen Kanal (direkt zum Thema, viraler Charakter)
- 7-8: Thematisch passend, wichtig, video-würdig
- 5-6: Nur am Rande relevant oder oberflächlich
- 1-4: Langweilig, technisch, lokal
- 0:   OFF-TOPIC (nicht verwandt mit Kanal-Schlüsselwörtern) — egal wie spannend die Schlagzeile klingt, gib 0-3

MITTELPUNKT-REGEL: Das Thema des Kanals muss im MITTELPUNKT stehen; eine bloße
Erwähnung reicht nicht. Eine Meldung über einen Rivalen oder eine andere Person
(z. B. das Vorspiel-Zitat eines gegnerischen Spielers, der eigene Transfer eines
anderen Vereins) ist hier OFF-TOPIC → gib 0-3. Prüfung: Bleibt die Meldung ohne
das Kanal-Thema bestehen, ist sie off-topic.

EREIGNIS-TOR (gilt VOR der Mittelpunkt-Regel): Trägt die Schlagzeile kein
erzählbares EREIGNIS, gib 0-3 — auch wenn das Kanalthema genau im Mittelpunkt steht.
- KEIN Ereignis: Aufstellungen/Kaderlisten, Spielvorbereitung, Ankunft der
  Mannschaft in Stadt oder Stadion, Trainingsberichte, Jahrestage / "heute vor
  Jahren", Statistik-Übersichten, Tabellen, Spielernoten nach dem Spiel,
  PR-Meldungen von der EIGENEN Vereinsseite, Sende-/Programmhinweise, Umfragen,
  Kommentare, "Wer ist X"-Porträts.
- Ein EREIGNIS: Tor, Ergebnis, Rote Karte, bestätigter Transfer, Verletzung,
  Abgang, Sperre, Krise, wörtliches Zitat der beteiligten Person, Vereins- oder
  Verbandsentscheidung.
Prüfung: Beantwortet die Schlagzeile nicht "was ist PASSIERT?", gibt es kein
Ereignis → 0-3.

INTERAKTIONS-ACHSE (bei gleich wichtigen Meldungen entscheidet diese):
- HÖHER bewerten: Konflikt/Entscheidung — Angebot ABGELEHNT, Bedingungen, Krise,
  Veto, keine Zugeständnisse, feststehende Entscheidung, offizielle Erklärung,
  wörtliches Zitat der beteiligten Person
- NIEDRIGER bewerten: folgenlose Spekulation — "im Gespräch", "auf dem Radar",
  "interessiert", "beobachtet", "kommt er?"-Andeutungen
Gemessen: Konflikt-/Entscheidungsrahmen lag auf diesem Kanal 43% über dem
Median, vage Spekulation 12% darunter.

{scope_block}Schlagzeilen:
{listing}

Antworte NUR in diesem JSON-Format, kein anderer Text:
{{"scores": [{{"guid": "<gleich>", "score": <0-10>, "reasoning": "<≤200 char, warum>"}}, ...]}}""",
    "es": """Eres el editor de un canal de YouTube Shorts.

CANAL: {channel_name}
TEMA/PALABRAS CLAVE: {keywords}

Puntúa los siguientes titulares de 0 a 10 según su RELEVANCIA PARA ESTE CANAL y su interés:
- 9-10: Noticia de última hora muy potente para este canal (directamente del tema, viral)
- 7-8: Del tema, importante, merece un vídeo
- 5-6: Sólo tangencial o sin fondo
- 1-4: Aburrido, técnico, muy local
- 0:   FUERA DE TEMA (sin relación con las palabras clave) — por atractivo que suene el titular, puntúa 0-3

PUERTA DEL SUCESO (se aplica ANTES de la regla del centro): si el titular no
lleva ningún SUCESO que contar, puntúa 0-3 — aunque el sujeto del canal esté
justo en el centro.
- NO es un suceso: alineaciones y listas de convocados, la previa del partido,
  la llegada del equipo a la ciudad o al estadio, crónicas de entrenamiento,
  aniversarios / "tal día como hoy", recopilaciones de estadísticas, la
  clasificación, el uno a uno o los aprobados y suspensos tras el partido, las
  notas corporativas de la WEB OFICIAL del club, horarios y datos de emisión,
  encuestas, columnas de opinión, perfiles de "quién es X".
- SÍ es un suceso: un gol, un resultado, una roja, un fichaje confirmado, una
  lesión, una salida, una sanción, una crisis, una frase EN BOCA del propio
  protagonista, una decisión del club o de la federación.
Prueba: si el titular no responde a "¿qué ha PASADO?", no hay suceso → 0-3.

REGLA DEL CENTRO: El sujeto del canal debe estar en el CENTRO de la noticia; que
se le mencione de paso no basta. Una noticia centrada en un club rival o en otra
persona (p. ej. la declaración previa de un jugador rival, el fichaje propio de
otro equipo) está FUERA DE TEMA aquí → puntúa 0-3. Prueba: si la noticia se
sostiene al quitar el sujeto del canal, está fuera de tema.

EJE DE INTERACCIÓN (úsalo para desempatar entre noticias igual de importantes):
- SUBE: conflicto o decisión — oferta RECHAZADA, exigencias, crisis, veto,
  negativa a ceder, decisión ya tomada, comunicado oficial, cita directa de la
  persona implicada
- BAJA: especulación sin desenlace — "suena para", "en el radar", "interesa",
  "sigue de cerca", "¿fichará?" y contactos vagos
Medido: en este canal el encuadre de conflicto/decisión rindió un 43% por encima
de la mediana y la especulación vaga un 12% por debajo.

{scope_block}Titulares:
{listing}

Responde SÓLO en este formato JSON, sin ningún otro texto:
{{"scores": [{{"guid": "<el mismo>", "score": <0-10>, "reasoning": "<≤200 char, por qué esta nota>"}}, ...]}}""",
}


# Dikey bloğu: havuz zaten dikeye süzülmüş olarak geliyor (bkz.
# trends/verticals.py), ama kapı bunu BİLMEZSE varsayılan "fayda araması"
# listesini uygular ve para kanalında altın hareketini eler. Blok, o dikeyde
# neyin hikâye sayıldığını söyler.
#
# Diller mevcut şablonlarla aynı: tr/en/de; başka dil en'e düşer.
_VERTICAL_GATE: dict[str, dict[str, str]] = {
    "tr": {
        "_bas": """

BU KANALIN DİKEYİ: {label}
Havuz Google'ın KENDİ sınıflandırmasıyla süzüldü ve o sınıflandırma YANILIR.
Başlık bu dikeye AİT DEĞİLSE 0-3 ver — anlatılabilir bir olay olsa bile.
""",
        "para": "Bu dikeyde fiyat/kur/faiz HAREKETİNİN NEDENİ bir olaydır (rekor, karar, zam, iflas, satın alma) — 7-10 ver. Yalnız 'kaç TL / ne kadar' sorgusu olay DEĞİLDİR — 0-3 ver.",
        "spor": "Bu dikeyde skor, transfer, sakatlık, ayrılık, ceza ve resmi açıklama olaydır. 'Maç hangi kanalda / saat kaçta' olay değildir.",
        "magazin": "Bu dikeyde ayrılık, evlilik, dava, itiraf, kadro/yayın kararı ve vefat olaydır. 'Kimdir / kaç yaşında / nereli' olay değildir.",
        "adalet": "Bu dikeyde gözaltı, iddianame, duruşma kararı, ceza, tahliye ve resmi kurum kararı olaydır. Dava dosyası özeti ya da 'X kimdir' olay değildir.",
        "olay": "Bu dikeyde kaza, yangın, deprem, sel, kurtarma ve resmi uyarı olaydır. Hava durumu tahmini sorgusu olay değildir.",
        "teknoloji": "Bu dikeyde duyuru, çıkış, kapanma, ihlal, satın alma ve rekor olaydır. 'Fiyatı ne kadar / nasıl indirilir' olay değildir.",
    },
    "en": {
        "_bas": """

THIS CHANNEL'S VERTICAL: {label}
The pool was filtered by Google's OWN classification, which is often wrong.
If a headline does not belong to this vertical, score 0-3 — even if it is a real event.
""",
        "para": "Here, the REASON behind a price/rate move is an event (record, decision, hike, bankruptcy, acquisition) — score 7-10. A bare 'how much is it' lookup is NOT an event — score 0-3.",
        "spor": "Here, scores, transfers, injuries, exits, bans and official statements are events. 'What channel / what time is the match' is not.",
        "magazin": "Here, splits, marriages, lawsuits, confessions, casting/airing decisions and deaths are events. 'Who is X / how old' is not.",
        "adalet": "Here, arrests, indictments, rulings, sentences, releases and official decisions are events. A case summary or 'who is X' is not.",
        "olay": "Here, crashes, fires, earthquakes, floods, rescues and official warnings are events. A weather forecast lookup is not.",
        "teknoloji": "Here, announcements, launches, shutdowns, breaches, acquisitions and records are events. 'How much does it cost / how to download' is not.",
    },
    "de": {
        "_bas": """

DIE VERTIKALE DIESES KANALS: {label}
Der Pool wurde nach Googles EIGENER Klassifikation gefiltert, und die irrt oft.
Gehört eine Schlagzeile nicht in diese Vertikale, gib 0-3 — auch bei echtem Ereignis.
""",
        "para": "Hier ist der GRUND einer Preis-/Kurs-/Zinsbewegung ein Ereignis (Rekord, Beschluss, Erhöhung, Insolvenz, Übernahme) — 7-10. Eine reine 'Wie viel kostet' Abfrage ist KEIN Ereignis — 0-3.",
        "spor": "Hier sind Ergebnisse, Transfers, Verletzungen, Abgänge, Sperren und offizielle Erklärungen Ereignisse. 'Welcher Sender / wann' nicht.",
        "magazin": "Hier sind Trennungen, Hochzeiten, Klagen, Geständnisse, Besetzungs-/Sendeentscheidungen und Todesfälle Ereignisse. 'Wer ist X / wie alt' nicht.",
        "adalet": "Hier sind Festnahmen, Anklagen, Urteile, Strafen, Freilassungen und Behördenentscheidungen Ereignisse. Eine Fallzusammenfassung nicht.",
        "olay": "Hier sind Unfälle, Brände, Erdbeben, Überschwemmungen, Rettungen und amtliche Warnungen Ereignisse. Eine Wettervorhersage nicht.",
        "teknoloji": "Hier sind Ankündigungen, Starts, Abschaltungen, Datenlecks, Übernahmen und Rekorde Ereignisse. 'Wie teuer / wie herunterladen' nicht.",
    },
}


def _vertical_gate_block(vertical: str | None, language: str) -> str:
    """Kapı prompt'una eklenecek dikey bloğu. Dikey yoksa boş dize."""
    if not vertical:
        return ""
    from short_bot.trends.verticals import VERTICAL_LABELS
    lang = (language or "tr").split("-")[0].lower()
    table = _VERTICAL_GATE.get(lang) or _VERTICAL_GATE["en"]
    label = VERTICAL_LABELS.get(vertical, vertical)
    parts = [table["_bas"].format(label=label).strip()]
    note = table.get(vertical)
    if note:
        parts.append(note)
    # Sonda BOŞ SATIR şart: blok, şablonda "{vertical_block}Başlıklar:" olarak
    # gömülü — ayırmazsak not satırı başlık listesine yapışır.
    return "\n".join(parts) + "\n\n"



_FOCUS_BASLIK = {
    "tr": ("KANALIN ODAĞI (dikeyin İÇİNDE bir tercih, yeni bir kapı DEĞİL):",
           "Bu odağa uyan başlığa 1-2 puan FAZLA ver. Uymayan başlık kendi "
           "değerinden puan alır — odağa uymuyor diye 4'ün altına İTME, ve "
           "olay olmayan bir başlığı odağa uyuyor diye 3'ün üstüne ÇIKARMA."),
    "en": ("CHANNEL FOCUS (a preference INSIDE this vertical, NOT another gate):",
           "Score a headline that matches this focus 1-2 points HIGHER. One that "
           "does not match still scores on its own merits — do NOT push it below 4 "
           "for missing the focus, and NEVER lift a non-event above 3."),
    "es": ("FOCO DEL CANAL (una preferencia DENTRO de esta vertical, NO otra puerta):",
           "Sube 1-2 puntos el titular que encaje con este foco. El que no encaje "
           "puntúa por sus propios méritos — NO lo bajes de 4 por no encajar, y "
           "NUNCA subas por encima de 3 un titular sin suceso."),
}


def _focus_block(focus: str, language: str) -> str:
    """Kanalın odak bloğu. Odak yoksa boş dize.

    Neden AYRI bir blok: dikey kapısı "bu bizim işimiz mi" diye sorar ve
    ELER. Odak elemez, SIRALAR — ikisini tek metne karıştırmak modelin
    uymayan haberi elemesine yol açardı ve dar dikeyde arz çöker.
    """
    focus = (focus or "").strip()
    if not focus:
        return ""
    lang = (language or "tr").split("-")[0].lower()
    baslik, kural = _FOCUS_BASLIK.get(lang) or _FOCUS_BASLIK["en"]
    return f"{baslik}\n{focus}\n{kural}\n\n"



# KANALIN KAPSAMI — KAPI.
#
# `_focus_block` bilinçli olarak SIRALAR, elemez. Kapsam ise eler ve gerekçesi
# ölçüldü: Real Madrid ve Galatasaray ÇOK BRANŞLI kulüpler. Puanlayıcıya
# söylenen tek kapsam ifadesi "TOPIC/KEYWORDS: Real Madrid" ve bir BASKETBOL
# haberi bunu gerçekten karşılıyor — merkez kuralı da geçiyor, çünkü haberin
# merkezinde sahiden Real Madrid var. Model doğru puanlıyor; ona yanlış soru
# soruluyordu.
#
# ÖLÇÜLDÜ (2026-08-22): latidoblanco-flash'ta #1826 "Real Madrid Baloncesto"
# haberi üretildi; galatasaray'da 25 günde 7 basketbol + 1 voleybol videosu
# çıktı (#1340, #1316, #1308, #1302, #1289, #1275, #1296). Senaryonun
# `category` alanı zaten "basketbol" yazıyordu — sistem sporu BİLİYOR, kimse
# ona göre elemiyordu.
_KAPSAM_BASLIK = {
    "tr": ("KANALIN KAPSAMI (KAPI — haberin buraya ait olup olmadığına bu karar verir):",
           "Kapsam dışındaki başlık, haber ne kadar güçlü olursa olsun 0-2 alır. "
           "Kararsız kalırsan kapsam DIŞI say: kanal dar kalsın, konusu kaysın istemiyoruz."),
    "en": ("CHANNEL SCOPE (a GATE — this decides whether the story belongs here at all):",
           "A headline outside this scope scores 0-2, no matter how strong the news is. "
           "When in doubt, treat it as OUT of scope: a narrow channel is fine, a drifting one is not."),
    "de": ("KANALUMFANG (TOR — hiermit wird entschieden, ob die Meldung hierher gehört):",
           "Eine Schlagzeile außerhalb dieses Umfangs bekommt 0-2, egal wie stark die "
           "Nachricht ist. Im Zweifel AUSSERHALB: ein enger Kanal ist in Ordnung, "
           "ein abdriftender nicht."),
    "es": ("ÁMBITO DEL CANAL (una PUERTA — decide si la noticia pertenece aquí):",
           "Un titular fuera de este ámbito recibe 0-2, por fuerte que sea la noticia. "
           "En caso de duda, dalo por FUERA: preferimos un canal estrecho a uno que se desvía."),
}


def _scope_block(scope: str, language: str) -> str:
    """Kanalın kapsam kapısı. Kapsam tanımlı değilse boş dize (eski davranış)."""
    scope = (scope or "").strip()
    if not scope:
        return ""
    lang = (language or "tr").split("-")[0].lower()
    baslik, kural = _KAPSAM_BASLIK.get(lang) or _KAPSAM_BASLIK["en"]
    # Sonda BOŞ SATIR şart: blok şablona "{scope_block}Başlıklar:" olarak girer.
    return f"{baslik}\n{scope}\n{kural}\n\n"


# Trend kanalı (content_source="trends"): kanalın ÖZNESİ yok, her konu uygun.
# Merkez kuralı uygulanmaz. Kapı tek şeyi eler: arkasında anlatılacak OLAY
# olmayan "fayda araması" (hava durumu, hisse fiyatı, maç hangi kanalda, TV
# program, sınav sonucu sorgusu). Sıralamayı puan DEĞİL arama hacmi yapar
# (select_by_volume); puan yalnız min_score eşiğinde kapı görevi görür.
_TREND_PROMPT_TEMPLATES = {
    "tr": """Sen bir YouTube Shorts gündem kanalının editörüsün. Kanal ülkenin o an
EN ÇOK ARANAN konularını 6 saniyelik tek kartta verir: manşet + 3-4 cümle gövde
+ fotoğraf. Aşağıdaki başlıklar Google Trends'ten geldi; her satırda arama
hacmi ve ilişkili aramalar var.

KANAL: {channel_name}

Her başlığı "bu bir OLAY mı, yoksa sadece bir ARAMA mı?" sorusuyla 0-10 puanla:
- 9-10: Net, anlatılabilir olay; tek kartta özetlenir (deprem uyarısı, kaza,
  zam kararı, transfer teklifi, resmi açıklama, skor + sonuç, gözaltı)
- 7-8: Olay var, biraz bağlam gerekir ama 3-4 cümleye sığar
- 4-6: Olay zayıf, yerel ya da yalnız bir kesimi ilgilendiriyor
- 0-3: FAYDA ARAMASI — arkasında haber yok: hava durumu, hisse fiyatı/grafik,
  döviz/altın kuru sorgusu, "maç hangi kanalda / saat kaçta", TV program ya da
  "son bölüm izle", "ne kadar kazandı / kimdir" (olay yok), sınav sonucu ve
  başvuru tarihi sorguları, ürün/kampanya fiyatı

Başlık ilgi çekici olsa bile OLAY yoksa 0-3 ver; izleyici 6 saniyede "ne oldu?"
sorusunun cevabını almalı. Arama hacmi yüksek diye puanı YÜKSELTME — hacmi
sistem ayrıca kullanıyor, sen yalnız olay var mı yok mu ona bak.

{vertical_block}Başlıklar:
{listing}

SADECE şu JSON formatında yanıtla, başka metin yazma:
{{"scores": [{{"guid": "<aynısı>", "score": <0-10>, "reasoning": "<≤200 char, neden bu puan>"}}, ...]}}""",

    "en": """You are the editor of a YouTube Shorts trending-news channel. The channel
turns the country's MOST-SEARCHED topics of the moment into a single 6-second
card: headline + 3-4 sentence body + photo. The headlines below come from
Google Trends; each line carries search volume and related queries.

CHANNEL: {channel_name}

Score each headline 0-10 by asking "is this an EVENT, or just a SEARCH?":
- 9-10: Clear, tellable event that fits one card (earthquake warning, crash,
  pay-rise decision, transfer bid, official statement, score + outcome, arrest)
- 7-8: An event, needs a little context but fits 3-4 sentences
- 4-6: Weak, local, or relevant to a narrow group only
- 0-3: UTILITY SEARCH — no story behind it: weather, stock price/chart,
  currency/gold rate lookup, "what channel / what time is the match", TV
  schedule or "watch latest episode", "how much did X earn / who is X" with no
  event, exam results and application dates, product/deal prices

Even if the headline is catchy, score 0-3 when there is no EVENT; the viewer
must get "what happened?" answered in 6 seconds. Do NOT raise the score for
high search volume — the system uses volume separately; you only judge
whether there is an event.

{vertical_block}Headlines:
{listing}

Reply ONLY in this JSON format, no other text:
{{"scores": [{{"guid": "<same>", "score": <0-10>, "reasoning": "<≤200 char, why this score>"}}, ...]}}""",

    "de": """Du bist Redakteur eines YouTube-Shorts-Kanals für aktuelle Trends. Der
Kanal macht aus den MEISTGESUCHTEN Themen des Landes eine einzige 6-Sekunden-
Karte: Schlagzeile + 3-4 Sätze + Foto. Die Schlagzeilen unten stammen aus
Google Trends; jede Zeile trägt Suchvolumen und verwandte Suchanfragen.

KANAL: {channel_name}

Bewerte jede Schlagzeile von 0-10 mit der Frage "ist das ein EREIGNIS oder nur
eine SUCHE?":
- 9-10: Klares, erzählbares Ereignis, passt auf eine Karte (Erdbebenwarnung,
  Unfall, Lohnentscheidung, Transferangebot, offizielle Erklärung, Ergebnis +
  Folge, Festnahme)
- 7-8: Ereignis vorhanden, braucht etwas Kontext, passt aber in 3-4 Sätze
- 4-6: Schwaches, lokales oder nur für eine kleine Gruppe relevantes Ereignis
- 0-3: NUTZSUCHE — keine Geschichte dahinter: Wetter, Aktienkurs/Chart,
  Wechselkurs/Goldpreis, "welcher Sender / wann läuft das Spiel", TV-Programm
  oder "letzte Folge ansehen", "wie viel hat X verdient / wer ist X" ohne
  Ereignis, Prüfungsergebnisse und Bewerbungsfristen, Produkt-/Angebotspreise

Auch bei reizvoller Schlagzeile: ohne EREIGNIS 0-3. Der Zuschauer muss in 6
Sekunden "was ist passiert?" beantwortet bekommen. Erhöhe die Bewertung NICHT
wegen hohen Suchvolumens — das System nutzt das Volumen separat; du beurteilst
nur, ob ein Ereignis vorliegt.

{vertical_block}Schlagzeilen:
{listing}

Antworte NUR in diesem JSON-Format, kein anderer Text:
{{"scores": [{{"guid": "<gleich>", "score": <0-10>, "reasoning": "<≤200 char, warum>"}}, ...]}}""",
}


def build_scoring_prompt(
    items: list[NewsItem],
    *,
    channel: "ChannelConfig | None" = None,
    performance_insights: dict | None = None,
) -> str:
    is_trends = channel is not None and channel.content_source == "trends"
    if is_trends:
        # Trend satırında bağlam (hacim + ilişkili aramalar) description'da
        # taşınıyor; model "ajet" gibi tek başına anlamsız terimi böyle çözer.
        listing = "\n".join(
            f"- guid={i.guid} | {i.title}" + (f" — {i.description}" if i.description else "")
            for i in items)
    else:
        listing = "\n".join(f"- guid={i.guid} | {i.title}" for i in items)
    if channel is None:
        # Backward-compat fallback: legacy callers (no channel context). Use
        # generic Turkish prompt without channel anchoring.
        return (
            "Aşağıdaki haber başlıklarını bir YouTube Shorts kanalı için "
            "ilginçlik/önem açısından 0-10 arası puanla. 9-10 = son dakika çok etkileyici "
            "(deprem, kritik karar, şok haber); 7-8 = önemli ama bekleyebilir; "
            "5-6 = ilginç ama derinliği yok; 0-4 = sıkıcı/teknik/lokal.\n\n"
            f"Başlıklar:\n{listing}\n\n"
            "SADECE şu JSON formatında yanıtla, başka metin yazma:\n"
            '{"scores": [{"guid": "<aynısı>", "score": <0-10>, "reasoning": "<≤200 char>"}, ...]}'
        )
    if is_trends:
        template = _TREND_PROMPT_TEMPLATES.get(channel.language, _TREND_PROMPT_TEMPLATES["en"])
    else:
        template = _PROMPT_TEMPLATES.get(channel.language, _PROMPT_TEMPLATES["en"])
    keywords_str = ", ".join(channel.keywords) if channel.keywords else "(no keywords)"
    # Kapsam kapısı HER kaynak türünde geçerli: çok branşlı bir kulüp kanalı
    # besleme de okusa trend de okusa aynı sızıntıyı yaşıyor. Besleme şablonu
    # `{scope_block}` yer tutucusunu taşır; trend şablonunda yer tutucu yok,
    # bu yüzden dikey zincirinin BAŞINA eklenir (str.format fazladan anahtarı
    # yok sayar, iki kez basılmaz).
    kapsam = _scope_block(getattr(channel, "scope", ""), channel.language)
    base = template.format(
        channel_name=channel.name,
        keywords=keywords_str,
        listing=listing,
        scope_block=kapsam,
        # Dikey bloğu başlık listesinin ÖNÜNE girer: prompt'un SON talimatı
        # çıktı biçimi (JSON) olmalı, sonrasına metin eklenmemeli.
        vertical_block=((kapsam
                         + _vertical_gate_block(channel.trends_vertical,
                                                channel.language)
                         + _focus_block(getattr(channel, "trends_focus", ""),
                                        channel.language))
                        if is_trends else ""),
    )
    # Canonical kategori: kanal liste tanımladıysa her başlık için konu iste.
    # Konu bilgisi seçim anında gerekiyor (kota tavanı buna dayanıyor) —
    # script'in kendi kategorisi seçimden SONRA yazılıyor, yani geç kalıyor.
    if channel.categories:
        allowed = " | ".join(channel.categories)
        base = base + (
            f"\n\nAyrıca her başlığa bu listeden BİR kategori ata (birebir, "
            f"listeden başka değer yazma): {allowed}\n"
            f'JSON alanı: "category": "<listeden biri>"'
        )
    # Saga anahtarı: aynı hikâyenin kaçıncı videosu olduğunu seçim anında
    # bilmek gerekiyor. Yalnız özellik açıkken sorulur — kapalı kanalların
    # prompt'u bit bit aynı kalsın.
    if channel.saga_penalty_per_repeat:
        base = base + (
            "\n\nAyrıca her başlığa haberin MERKEZİNDEKİ özneyi ata: transferi "
            f"ya da haberi yapılan KİŞİ veya KULÜP. \"{channel.name}\" ve "
            f"\"{keywords_str}\" içindeki kanal öznesini ASLA yazma — her "
            "haberde geçtiği için anahtar olarak işe yaramaz.\n"
            "Kişide YALNIZ SOYADI yaz (\"batrakov\", \"leao\"), kulüpte kısa "
            "ad (\"milan\"). Küçük harf, tek kelime tercih et. Aynı kişi her "
            "koşuda AYNI yazılmalı. Merkezde belirgin bir özne yoksa boş bırak.\n"
            'JSON alanı: "subject": "<soyadı veya kısa kulüp adı>"'
        )
    # Optional performance-feedback hint. format_scorer_hint returns "" when
    # the insight set is too sparse (<5 samples) so callers can pass freely
    # without worrying about anchoring on noise.
    if performance_insights:
        from short_bot.learning.injection import format_scorer_hint
        hint = format_scorer_hint(performance_insights)
        if hint:
            base = base + "\n\n" + hint
    return base


_BATCH_SIZE = 30   # tighter batches keep Haiku responses fast and well within
                   # context. Tested at 30 items the model returns in 5-15s;
                   # 100+ items sometimes time out or return truncated JSON.


def score_items(
    items: list[NewsItem],
    *,
    claude_path: str = "claude",
    model: str = "default",
    batch_size: int = _BATCH_SIZE,
    channel: "ChannelConfig | None" = None,
    performance_insights: dict | None = None,
    backend: str = "claude_cli",
    api_key: str | None = None,
) -> list[ScoredItem]:
    if not items:
        return []
    by_guid = {i.guid: i for i in items}
    out: list[ScoredItem] = []
    # Batch to avoid timeouts on large feeds. Each batch is an independent
    # claude call — failures in one batch shouldn't kill the whole run.
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        prompt = build_scoring_prompt(
            batch, channel=channel,
            performance_insights=performance_insights,
        )
        try:
            response = run_json(
                prompt, _ScoreResponse,
                claude_path=claude_path, model=model,
                backend=backend, api_key=api_key,
            )
        except OpenRouterError:
            # Permanent failure (bad/missing API key, quota exhausted, etc.).
            # Re-raise immediately — retrying every batch would just repeat the
            # same error silently, leaving the pipeline with an empty result and
            # no explanation.
            raise
        except Exception:
            # Transient batch failure (timeout, parse error, etc.): skip this
            # batch and score the rest. Better to lose some candidates than to
            # fail the entire run.
            continue
        for s in response.scores:
            item = by_guid.get(s.guid)
            if item is None:
                continue
            out.append(ScoredItem(item=item, score=s.score,
                                  reasoning=s.reasoning,
                                  category=normalize_category(s.category)
                                           if s.category else "",
                                  subject=normalize_subject(s.subject)))
    return out


_QUOTA_PENALTY = 3.0


def apply_category_quota(
    scored: list[ScoredItem],
    *,
    produced: dict[str, int],
    quota: dict[str, int],
    penalty: float = _QUOTA_PENALTY,
    floor: float = 0.0,
) -> list[ScoredItem]:
    """Kotasını doldurmuş kategorilerdeki adayların puanını düşür.

    ELEMEK yerine CEZA veriyoruz: transfer dönemi gibi haber akışının tek
    konuya kilitlendiği günlerde eleme üretimi tamamen durdururdu. Ceza ise
    "başka konu varsa onu seç, hiç yoksa yine de üret" davranışı verir.

    `floor` (pipeline min_score'u geçirir) cezanın adayı EŞİĞİN ALTINA
    itmesini engeller. Bu taban olmadan kota aday havuzunu zayıflatıyordu:
    gerçek koşuda güçlü GS haberleri 6.0'ın altına düştü, geriye 2 zayıf aday
    kaldı ve tam sınırdaki alakasız bir haber seçilerek Galatasaray kanalında
    Çorum FK videosu üretildi. Kota SIRALAMAYI değiştirmeli, kaliteyi değil.

    `produced`: son pencerede o kategoriden kaç video üretildiği.
    `quota`: kategori başına üst sınır. Listede olmayan kategori sınırsızdır.
    """
    if not quota:
        return scored
    out: list[ScoredItem] = []
    for s in scored:
        limit = quota.get(s.category) if s.category else None
        if limit is not None and produced.get(s.category, 0) >= limit:
            cezali = max(0.0, s.score - penalty)
            # Zaten tabanın altındaysa yükseltme — yalnız ceza sonucu düşmeyi
            # engelle.
            out.append(replace(s, score=max(cezali, min(floor, s.score))))
        else:
            out.append(s)
    return out


def select_top(scored: list[ScoredItem], min_score: float, n: int = 1) -> list[ScoredItem]:
    above = [s for s in scored if s.score >= min_score]
    above.sort(key=lambda s: s.score, reverse=True)
    return above[:n]


def select_by_volume(
    scored: list[ScoredItem], min_score: float, n: int = 1,
    *, intent: str = "any", language: str = "tr",
) -> list[ScoredItem]:
    """Trend kanalı seçimi: min_score eşiğini geçenler arasından en yüksek
    ARAMA HACMİ (item.trend_volume) önce, eşitlikte puan. Puan burada sıra
    değil KAPI — 'hikâyesiz fayda araması' eşiğin altında kalıp elenir,
    kalanları ülkenin ne aradığı sıralar.

    ``intent`` (bkz. ChannelConfig.trends_intent) hacimden ÖNCE gelen bir
    tercih basamağı ekler; filtre değildir, tercih edilen tür yoksa liste
    yine dolu döner:
        "question" — ilişkili aramalarında soru olanlar önce
        "breaking" — soru taşımayanlar (saf olay) önce
        "any"      — eski davranış, yalnız hacim
    """
    above = [s for s in scored if s.score >= min_score]
    if intent in ("question", "breaking"):
        from short_bot.search_intent import has_question_intent
        want_q = intent == "question"

        def _pref(s: ScoredItem) -> int:
            return int(has_question_intent(s.item, language=language) == want_q)
    else:
        def _pref(s: ScoredItem) -> int:
            return 0
    above.sort(key=lambda s: (_pref(s), s.item.trend_volume, s.score), reverse=True)
    return above[:n]


def select_newest_above(
    scored: list[ScoredItem], min_score: float, n: int = 1,
) -> list[ScoredItem]:
    """Hibrit seçim: min_score eşiğini geçenler arasından EN YENİ pub_date'e
    göre sırala, ilk n'i döndür. pub_date None olanlar en eskiye konur
    (datetime.min). select_top puana göre sıralarken bu tazeliğe göre sıralar."""
    from datetime import datetime, timezone
    above = [s for s in scored if s.score >= min_score]

    def _key(s: ScoredItem):
        pd = s.item.pub_date
        if pd is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return pd if pd.tzinfo else pd.replace(tzinfo=timezone.utc)

    above.sort(key=_key, reverse=True)
    return above[:n]


def saga_repeat_count(subject: str, produced: dict[str, int]) -> int:
    """`subject` ile aynı sagaya işaret eden üretilmiş video sayısı.

    Anahtar biçimi koşudan koşuya oynayabildiği için düz sözlük araması
    yetmez; `subject_matches` kelime-kümesi kuralını uygular.
    """
    if not subject:
        return 0
    return sum(n for key, n in produced.items() if subject_matches(subject, key))


def apply_saga_penalty(
    scored: list[ScoredItem],
    *,
    produced: dict[str, int],
    step: float,
) -> list[ScoredItem]:
    """Aynı öznenin tekrarında puanı kademeli düşür. TABAN YOK.

    `apply_category_quota`'dan AYRILAN NOKTA budur: kota `floor` alır ve
    cezanın adayı `min_score` altına itmesini engeller, çünkü kota SIRALAMA
    aracıdır. Saga sınırı ise VETO aracıdır — aynı hikâyenin altıncı videosu
    hiç çıkmamalıdır, zayıf bir alternatifle yer değiştirmesi bile gerekmez.

    Ölçüm gerekçesi (2026-08-18, 29 gün): üretilen 292 videonun yalnız 168'i
    yüklendi. Boş geçen bir koşu, yüklenmeyecek bir videodan ucuzdur.

    `produced`: son pencerede özne başına üretilen video sayısı
                (`db.count_recent_subjects`).
    `step`:     tekrar başına düşülecek puan. 0.0 = özellik kapalı.

    Boş özne (`subject=""`) hiç cezalandırılmaz — `saga_repeat_count` bunun
    için 0 döner; öznesiz aday ilk kez üretiliyormuş gibi geçer, dev bir
    "bilinmeyen" sagasına toplanmaz.
    """
    if not step:
        return scored
    out: list[ScoredItem] = []
    for s in scored:
        n = saga_repeat_count(s.subject, produced)
        if n:
            out.append(replace(s, score=max(0.0, s.score - step * n)))
        else:
            out.append(s)
    return out
