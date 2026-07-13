"""Reel (footage-sürüklü) domain modelleri.

Segment indeksleme (TimedWord.seg): 0=hook, 1..N=beats, N+1=close.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from short_bot.caption_align import align_to_asr
from short_bot.text_normalize import strip_non_turkish_diacritics


class ReelBeat(BaseModel):
    text: str = Field(min_length=8, max_length=300)
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


class ReelNarration(BaseModel):
    hook: str = Field(min_length=5, max_length=140)
    beats: list[ReelBeat] = Field(min_length=3, max_length=6)
    close: str = Field(min_length=5, max_length=CLOSE_MAX_CHARS)
    # İKİLİ yorum sorusu (opsiyonel). Taşarsa KIRPILIR — bir karakterlik taşma
    # yüzünden koca bir üretim (LLM + TTS + footage + montaj) çöpe gitmemeli.
    comment: str = Field(default="", max_length=COMMENT_MAX_CHARS)
    mood: Literal["upbeat", "neutral", "calm"]
    # Hook/close KENDİ görsel sorgusu (İngilizce stok araması). Boşsa ilk/son
    # beat'in sorgusu ödünç alınır (eski davranış). Hook videonun en kritik
    # karesi — kendi vurucu görselini hak eder (gerçek şikâyet: "ilk girişteki
    # görüntü alakasız" — hook, soyut bir beat sorgusunun çöp fallback'ini almıştı).
    hook_visual: str = Field(default="", max_length=120)
    close_visual: str = Field(default="", max_length=120)
    # TEPE: videonun EN BÜYÜK reveal'inin hangi beat olduğu. Beğeni tetiği ve abone
    # isteği buna göre yerleşir — ikisi de tepeden SONRA gelmeli. Beğeni bir karar
    # değil DUYGUSAL BOŞALMADIR; boşalacak bir tepe yoksa beğeni de gelmez.
    # -1 = LLM söylemedi → ORTA beat varsayılır ("en iyi bilgiyi öne koyma" hatasına
    # düşmektense ortaya varsay).
    peak_beat: int = Field(default=-1)

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

    def peak_segment(self) -> int:
        """Tepenin SEGMENT indeksi (hook segment 0 olduğu için +1)."""
        return self.peak_beat + 1

    def close_echoes_hook(self) -> bool:
        """LOOP kontrolü: kapanış hook'un sözcüklerini geri çağırıyor mu?

        Kapanış hook'la hiç ortak İÇERİK sözcüğü paylaşmıyorsa video 'biter' ve
        izleyici döngüye girmez — oysa her tekrar oynatma ayrı bir izlenme sayılır.
        """
        def _content_words(s: str) -> set[str]:
            import re
            words = re.findall(r"\w+", s.lower())
            return {w for w in words if len(w) >= 4}   # ek/edat gürültüsünü at

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
    )
