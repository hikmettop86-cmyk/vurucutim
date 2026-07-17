"""Reel (footage-sürüklü) domain modelleri.

Segment indeksleme (TimedWord.seg): 0=hook, 1..N=beats, N+1=close.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from short_bot.caption_align import align_to_asr
from short_bot.text_normalize import strip_non_turkish_diacritics


def _cumleler(s: str) -> list[str]:
    """Cümlelere böl. Kısaltma/ondalık ayırt etmez — kapanış/yorum için yeter."""
    import re
    return [c.strip() for c in re.split(r"(?<=[.!?…])\s+", (s or "").strip())
            if c.strip()]


def _content_words(s: str) -> set[str]:
    """Anlam taşıyan sözcükler (ek/edat gürültüsü elenir).

    İki denetim de buna dayanır: close_echoes_hook (loop) ve open_loop_spoken (takas).
    """
    import re
    return {w for w in re.findall(r"\w+", (s or "").lower()) if len(w) >= 4}


class ReelBeat(BaseModel):
    # 300→500: sahne modu + 90-140sn uzunluk daha zengin beat'ler üretiyor (benzetme +
    # diyalog). Uzun beat sorun değil — fast_cuts onu alt-kesimlere böler (footage
    # değişir, donuk kuyruk olmaz) ve karaoke altyazı zaten kelime kelime akar.
    text: str = Field(min_length=8, max_length=500)
    visual_query: str = Field(min_length=2, max_length=120)
    keyword: str = Field(default="", max_length=40)

    @field_validator("text", "keyword", mode="before")
    @classmethod
    def _norm(cls, v):
        return strip_non_turkish_diacritics(v) if isinstance(v, str) else v

    @field_validator("visual_query")
    @classmethod
    def _query_nonblank(cls, v):
        if not (v or "").strip():
            raise ValueError("visual_query boş olamaz")
        return v.strip()


# Kapanış DAR: uzun kapanış close segmentini şişirir (bir koşuda videonun %27'si)
# ve ekranı 13 saniye statik bir metin bloğu kaplar. Araştırma: outro ≤5sn, statik
# son kare LOOP'U ÖLDÜRÜR — izleyici bittiğini görür, başa dönmez.
CLOSE_MAX_CHARS = 120
# Yorum sorusu AYRI alan: close'a sığdırılınca 160 karakter sınırını aşıp ÜRETİMİ
# DÜŞÜRÜYORDU. İkisi de KONUŞULUR ama dev kapanış kartı yalnız callback'i gösterir.
COMMENT_MAX_CHARS = 90

# KARE SIFIR = KÜÇÜK RESİM. Feed'de gördüğü İLK KARE, izleyicinin durup durmayacağına
# karar verdiği karedir — ve video orada ~300px genişliğinde görünür. Bugün o karede
# HOOK CÜMLESİ duruyor: 140 karaktere kadar, otomatik sığdırma yüzünden 57 puntoya
# kadar inebilen bir metin bloğu. Kaydıran göz onu OKUMAZ; okunmayan hook, hook değildir.
# ``cover_title`` 3-6 kelimelik bir MANŞETTİR: küçük resim boyutunda bile okunur.
# Konuşulmaz — yalnız ekranda durur; hook CÜMLESİ altyazı olarak akmaya devam eder.
# Boşsa eski davranışa düşülür (hook cümlesi kartta) — fail-open.
COVER_TITLE_MAX_CHARS = 40
COVER_TITLE_MAX_WORDS = 6
# SEO VİDEO BAŞLIĞI üst sınırı. cover_title EKRAN manşetidir (kısa, metafor);
# title YouTube/dosya başlığıdır — özne anahtar-kelimesi önde + mahalle vuruşu.
# YouTube sert sınırı 100; Shorts için 90 tut (kısa+net). Taşarsa KIRPILIR (reddetme).
TITLE_MAX_CHARS = 90

# AÇIK KAPI: tek cümlelik, SPESİFİK bir vaat. Bir sonraki bölümün konu tohumu olacağı
# için "daha fazlası var" gibi içi boş bir cümle işe yaramaz — tohum olacak kadar
# somut olmalı. Uzun olması da gerekmiyor: tek nefeste söylenen bir söz.
OPEN_LOOP_MAX_CHARS = 140


class ReelNarration(BaseModel):
    hook: str = Field(min_length=5, max_length=140)
    beats: list[ReelBeat] = Field(min_length=3, max_length=6)
    close: str = Field(min_length=5, max_length=CLOSE_MAX_CHARS)
    # İKİLİ yorum sorusu (opsiyonel). Taşarsa KIRPILIR — bir karakterlik taşma
    # yüzünden koca bir üretim (LLM + TTS + footage + montaj) çöpe gitmemeli.
    comment: str = Field(default="", max_length=COMMENT_MAX_CHARS)
    mood: Literal["upbeat", "neutral", "calm"]

    @field_validator("mood", mode="before")
    @classmethod
    def _mood_zorla(cls, v):
        """mood bir İPUCUDUR (müzik seçimi) — geçersiz etiket üretimi ÖLDÜREMEZ.

        GERÇEK HATA (keşif modu ilk koşusu): model 3 denemede de mood='mizahi ve
        enerjik' yazdı → Literal doğrulaması üretimi düşürdü. Serbest metin en
        yakın kovaya zorlanır; emin olunamazsa 'upbeat' (mizah kanalı varsayılanı)."""
        if isinstance(v, str) and v not in ("upbeat", "neutral", "calm"):
            s = v.lower()
            if any(k in s for k in ("calm", "sakin", "hüzün", "huzun", "yavaş", "yavas")):
                return "calm"
            if any(k in s for k in ("neutral", "nötr", "notr", "ciddi")):
                return "neutral"
            return "upbeat"
        return v
    # Hook/close KENDİ görsel sorgusu (İngilizce stok araması). Boşsa ilk/son
    # beat'in sorgusu ödünç alınır (eski davranış). Hook videonun en kritik
    # karesi — kendi vurucu görselini hak eder (gerçek şikâyet: "ilk girişteki
    # görüntü alakasız" — hook, soyut bir beat sorgusunun çöp fallback'ini almıştı).
    hook_visual: str = Field(default="", max_length=120)
    close_visual: str = Field(default="", max_length=120)
    # Kare-sıfır manşeti (3-6 kelime). Konuşulmaz, yalnız ekranda durur.
    cover_title: str = Field(default="", max_length=COVER_TITLE_MAX_CHARS)
    # SEO VİDEO BAŞLIĞI (YouTube + dosya adı). cover_title EKRAN manşeti (metafor);
    # bu ise ÖZNE anahtar-kelimesi ÖNDE (aramada bulunsun) + kısa mahalle vuruşu.
    # Boşsa çağıran uzun konu metnine düşer (geriye uyum, sıfır regresyon).
    title: str = Field(default="", max_length=TITLE_MAX_CHARS)
    # İNGİLİZCE BAŞLIK (kürate): YouTube çok-dilli başlık → küresel Shorts akışı (240 ülke).
    # Boşsa yalnız TR başlık kullanılır (geriye uyum).
    title_en: str = Field(default="", max_length=TITLE_MAX_CHARS)
    # AÇIK KAPI: bu bölümün tepesi ödendikten SONRA açılan yeni, spesifik soru.
    # Bir sonraki bölümün KONU TOHUMUDUR (bkz. reel_series) — abone isteğini bir
    # ricadan TAKASA çeviren şey budur. Cümlenin kendisi tepe-sonrası beat'in
    # METNİNE dokunur (orada konuşulur); bu alan onun YAPISAL kaydıdır.
    open_loop: str = Field(default="", max_length=OPEN_LOOP_MAX_CHARS)
    # TEPE: videonun EN BÜYÜK reveal'inin hangi beat olduğu. Beğeni tetiği ve abone
    # isteği buna göre yerleşir — ikisi de tepeden SONRA gelmeli. Beğeni bir karar
    # değil DUYGUSAL BOŞALMADIR; boşalacak bir tepe yoksa beğeni de gelmez.
    # -1 = LLM söylemedi → ORTA beat varsayılır ("en iyi bilgiyi öne koyma" hatasına
    # düşmektense ortaya varsay).
    peak_beat: int = Field(default=-1)
    # --- MERAK MİMARİSİ (spec 2026-07-16) — hepsi varsayılan-boş (geriye uyum) ---
    # Hook'un açtığı merak sorusu; ekranda küçük çip olarak asılı kalır ve reveal
    # anında 'cevaplandı'ya döner. Kırpılır, reddedilmez (comment/cover_title dersi).
    open_question: str = Field(default="", max_length=200)
    # Cevabın ödendiği beat (0-tabanlı). -1 = belirtilmedi → peak_beat kullanılır.
    reveal_beat: int = Field(default=-1)
    # Adayın klipleri DRAMATURJİYE göre dizmesi: beat i, orijinal kliplerden
    # clip_order[i]'yi anlatır. Permütasyon değilse boşaltılır (kimlik sırası).
    clip_order: list[int] = Field(default_factory=list)

    @field_validator("open_question", mode="before")
    @classmethod
    def _oq_kirp(cls, v):
        if not isinstance(v, str):
            return ""
        v = strip_non_turkish_diacritics(v).strip()
        return v[:48].rstrip() if len(v) > 48 else v

    @model_validator(mode="after")
    def _merak_alanlarini_kelepcele(self):
        """Merak alanları İPUCUDUR — geçersiz değer üretimi ÖLDÜREMEZ (mood dersi)."""
        n = len(self.beats)
        if self.reveal_beat >= n:
            self.reveal_beat = n - 1
        if self.reveal_beat < -1:
            self.reveal_beat = -1
        co = list(self.clip_order or [])
        if co and sorted(co) != list(range(n)):
            self.clip_order = []          # permütasyon değil → kimlik sırası
        return self

    @model_validator(mode="before")
    @classmethod
    def _soru_close_a_girmesin(cls, data):
        """Yorum sorusunu 'close' alanından SÖK, 'comment'e taşı.

        GERÇEK HATA (short 801 ve 802, Almanca): prompt kendisiyle çelişiyordu —
        şema "yorum sorusunu close'a KOYMA, ayrı alanı var" derken enjekte edilen
        yönerge "soruyu close'un SONUNA ekle" diyordu. Model ikisini de doldurdu:
          close   = "So wurde Löwenzahn zum Kaffeeersatz. Was schmeckt besser:
                     Wurzel A oder Blüte B? Nur A oder B."
          comment = "Was schmeckt wohl besser: Wurzel A oder Blüte B?"
        Sonuç: soru İKİ KEZ soruldu ve dev kapanış KARTI (yalnız close'u basar)
        7 satırlık metin duvarı oldu — videonun üçte biri boyunca ekranda kaldı.
        Ayrıca yönergedeki örnek kalıbın META-TALİMATI ("Schreib nur den
        Buchstaben") senaryoya "Nur A oder B." diye sızdı.

        Prompt düzeltildi, ama prompt kuralı TEK BAŞINA YETMEZ (bu oturumda üç kez
        kanıtlandı). Kural yapısal olduğu için kapı da deterministik:
        close bir LOOP CALLBACK'tir → ilk SORU cümlesinde ve sonrasında ne varsa
        close'a ait değildir. Kalıp talimatı da ("...Buchstaben") sorudan SONRA
        geldiği için aynı kesmeyle gider.

        Callback'i asla yok etme: sorudan ÖNCE hiçbir şey yoksa close'a dokunma
        (modelin sırayı ters kurduğu hâl — bozuk ama yıkmaktan iyidir).
        """
        if not isinstance(data, dict):
            return data
        close = (data.get("close") or "").strip()
        comment = (data.get("comment") or "").strip()
        if close:
            cumleler = _cumleler(close)
            ilk_soru = next((i for i, c in enumerate(cumleler) if c.endswith("?")), -1)
            if ilk_soru > 0:                       # sorudan ÖNCE callback var → kes
                data["close"] = " ".join(cumleler[:ilk_soru])
                if not comment:
                    comment = cumleler[ilk_soru]   # soruyu çöpe atma, kendi alanına taşı
        if comment:
            # comment YALNIZ soru cümlesi olsun: kalıbın talimat parçası buraya da
            # sızabilir ("Schreib nur den Buchstaben.").
            sorular = [c for c in _cumleler(comment) if c.endswith("?")]
            data["comment"] = sorular[0] if sorular else comment
        return data

    @field_validator("hook", "close", "comment", mode="before")
    @classmethod
    def _norm(cls, v):
        return strip_non_turkish_diacritics(v) if isinstance(v, str) else v

    @field_validator("comment", mode="before")
    @classmethod
    def _trim_comment(cls, v):
        """Taşan yorum sorusunu KIRP — üretimi düşürme (bkz. COMMENT_MAX_CHARS)."""
        if isinstance(v, str) and len(v) > COMMENT_MAX_CHARS:
            return v[:COMMENT_MAX_CHARS].rstrip()
        return v

    @field_validator("cover_title", mode="before")
    @classmethod
    def _fit_cover_title(cls, v):
        """Manşeti KELİME sınırına kırp — reddetme.

        LLM "3-6 kelime" talimatına uymayınca koca bir üretimi (LLM + TTS + footage
        + montaj) çöpe atmanın anlamı yok. Ama 12 kelimelik bir "manşet" manşet
        DEĞİLDİR — küçük resimde yine okunmaz. O yüzden reddetmek yerine KIRPIYORUZ:
        ilk 6 kelime zaten vaadin taşıyıcısıdır.
        """
        if not isinstance(v, str):
            return v
        s = strip_non_turkish_diacritics(v).strip()
        words = s.split()
        if len(words) > COVER_TITLE_MAX_WORDS:
            s = " ".join(words[:COVER_TITLE_MAX_WORDS])
        return s[:COVER_TITLE_MAX_CHARS].rstrip()

    @model_validator(mode="after")
    def _resolve_peak(self):
        """Tepeyi geçerli ARALIĞA otur: ne İLK ne SON beat olabilir.

        Prompt bunu söylüyor ama LLM uymuyor. GERÇEK HATA (short_id=750): 3 beat
        varken peak_beat=2 (SONUNCU) dendi → tepe videonun %80'ine kaydı → beğeni
        ve abone tetikleri sonda kaldı. Araştırma tepeyi ~%50'de istiyor.

        Kod ZORLAR: 3+ beat varsa tepe [1, n-2] aralığında; 2 beat varsa 0.
        Menzil dışı/uydurma indeks → ORTA beat (üretim asla çökmez).
        """
        n = len(self.beats)
        if not n:
            return self
        lo, hi = (1, n - 2) if n >= 3 else (0, max(0, n - 1))
        p = self.peak_beat
        if not (lo <= p <= hi):
            p = n // 2 if n >= 3 else 0
            p = min(max(p, lo), hi)
            object.__setattr__(self, "peak_beat", p)
        return self

    @field_validator("open_loop", mode="before")
    @classmethod
    def _trim_open_loop(cls, v):
        if isinstance(v, str):
            v = strip_non_turkish_diacritics(v).strip()
            return v[:OPEN_LOOP_MAX_CHARS].rstrip()
        return v

    @field_validator("title", mode="before")
    @classmethod
    def _trim_title(cls, v):
        """SEO başlığını KIRP — bir karakterlik taşma koca üretimi düşürmesin."""
        if isinstance(v, str):
            v = strip_non_turkish_diacritics(v).strip()
            return v[:TITLE_MAX_CHARS].rstrip()
        return v

    def peak_segment(self) -> int:
        """Tepenin SEGMENT indeksi (hook segment 0 olduğu için +1)."""
        return self.peak_beat + 1

    def open_loop_spoken(self) -> bool:
        """Açık kapı, TEPEDEN SONRAKİ beat'lerde GERÇEKTEN konuşuluyor mu?

        Abone çipi tepeden ~1.3sn sonra ekrana geliyor. Vaat o ana kadar SÖYLENMEMİŞSE
        istek boşa düşer: izleyici neyin karşılığında abone olacağını bilmez ve çip
        "daha fazlası için abone ol" beyaz gürültüsüne dönüşür.

        Prompt bunu istiyor ama LLM'e güvenmiyoruz — ölçüyoruz (bkz. close_echoes_hook:
        aynı gerekçe, aynı desen).
        """
        if not self.open_loop:
            return False
        vaat = _content_words(self.open_loop)
        if not vaat:
            return False
        sonrasi = " ".join(b.text for b in self.beats[self.peak_beat + 1:])
        ortak = vaat & _content_words(sonrasi)
        # Tek ortak kelime tesadüf olabilir ("bir", "şey" zaten elenmiş durumda);
        # ikisi, vaadin gerçekten dokunduğuna işaret eder.
        return len(ortak) >= 2

    def close_echoes_hook(self) -> bool:
        """LOOP kontrolü: kapanış hook'un sözcüklerini geri çağırıyor mu?

        Kapanış hook'la hiç ortak İÇERİK sözcüğü paylaşmıyorsa video 'biter' ve
        izleyici döngüye girmez — oysa her tekrar oynatma ayrı bir izlenme sayılır.
        """
        hook_w = _content_words(self.hook)
        return bool(hook_w and (hook_w & _content_words(self.close)))

    def segments(self) -> list[str]:
        """Konuşulan segmentler. Yorum sorusu KAPANIŞ SEGMENTİNİN sonuna eklenir:
        SESLİ sorulmazsa yanıt gelmez. Ama dev kapanış KARTI yalnız ``close``u
        gösterir (bkz. reel_render) — soru altyazıda okunur, ekranı kaplamaz."""
        close = f"{self.close} {self.comment}".strip() if self.comment else self.close
        return [self.hook, *[b.text for b in self.beats], close]

    def segment_queries(self) -> list[str | None]:
        """Segment başına footage sorgusu. hook/close kendi sorgusunu kullanır;
        boşsa None → çağıran ilk/son beat'in sorgusuna düşer."""
        hook_q = (self.hook_visual or "").strip() or None
        close_q = (self.close_visual or "").strip() or None
        return [hook_q, *[b.visual_query for b in self.beats], close_q]

    def segment_keywords(self) -> list[str]:
        return ["", *[b.keyword for b in self.beats], ""]

    def full_text(self) -> str:
        return " ".join(self.segments())

    def word_count(self) -> int:
        return len(self.full_text().split())


@dataclass(frozen=True)
class TimedWord:
    word: str
    start_s: float
    end_s: float
    seg: int


@dataclass(frozen=True)
class ReelTimeline:
    words: list[TimedWord]
    seg_spans: list[tuple[float, float]]   # her segmentin [start, end]'i
    seg_queries: list[str | None]          # footage sorgusu (hook/close None)
    seg_keywords: list[str]                # ekran kartı metni
    duration_s: float
    hook: str
    close: str
    cover_title: str = ""                  # kare-sıfır manşeti (boşsa hook cümlesi)


def build_reel_timeline(narration: "ReelNarration", asr_words: list[TimedWord],
                        *, duration_s: float) -> "ReelTimeline":
    if duration_s <= 0:
        raise ValueError(f"duration_s pozitif olmalı, got {duration_s}")

    words_flat: list[str] = []
    segs_flat: list[int] = []
    for seg_idx, seg_text in enumerate(narration.segments()):
        for w in seg_text.split():
            words_flat.append(w)
            segs_flat.append(seg_idx)

    times = align_to_asr(words_flat, asr_words, duration_s)

    timed = [TimedWord(word=w, start_s=t[0], end_s=t[1], seg=s)
             for w, s, t in zip(words_flat, segs_flat, times)]

    n_segs = len(narration.segments())
    seg_spans: list[tuple[float, float]] = []
    for si in range(n_segs):
        chunk = [tw for tw in timed if tw.seg == si]
        if chunk:
            seg_spans.append((chunk[0].start_s, chunk[-1].end_s))
        else:
            prev = seg_spans[-1][1] if seg_spans else 0.0
            seg_spans.append((prev, prev))

    return ReelTimeline(
        words=timed, seg_spans=seg_spans,
        seg_queries=narration.segment_queries(),
        seg_keywords=narration.segment_keywords(),
        duration_s=duration_s, hook=narration.hook, close=narration.close,
        cover_title=narration.cover_title,
    )
