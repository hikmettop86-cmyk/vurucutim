"""Tasarım dili kütüphanesi — `templates/design/*.md` uyarlayıcısı.

NEDEN: prompt eskiden İKİ ESKİ ŞABLONU örnek veriyordu ("yapıyı bunlardan al,
görünümü kopyalama"). Model onlara demir atıyordu ve üretilen her şablon aynı
kalıba benziyordu — kullanıcının şikâyeti buydu ("şablonlar birbirine
benzemesin", "yaratıcı bir modül lazım").

Artık her adaya FARKLI bir tasarım dili veriliyor. Diller
`VoltAgent/awesome-design-md` deposundan (MIT) olduğu gibi alındı; bkz.
`templates/design/LICENSE-VoltAgent.md`.

İKİ UYARLAMA ŞART:

1. AYIKLAMA — dosyaların ~%26'sı buton/input/form stilleri ve responsive
   breakpoint'ler. Bizim çıktımızda buton yok, tek bir SABİT 1080×1920 tuval
   var; o bölümler prompt'u şişirir ve modeli yanlış yönlendirir.

2. TUVAL ÇAPALARI — ölçüler web boyutunda yazılmış (Wired hero manşeti 64px),
   bizim manşetimiz 96-132px. Merdivenin ORANLARI taşınır, mutlak değerleri
   taşınmaz; çapaları prompt'a ekliyoruz ve ölçek çarpanını da söylüyoruz.

Konum `templates/design/`: `templates_dir` zaten her çağrıya parametreyle
gidiyor (paketlenmiş kurulumda da doğru çözülür). `TEMPLATE-SPEC.md` gibi
CWD'ye bağlı olsaydı depo dışı koşularda bulunamazdı — o tuzağa bir kez
düşüldü.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

# Prompt'a girmeyen bölümler. Başlık eşleşmesi BÜYÜK/küçük duyarsız ve
# "## " ile başlayan üst düzey bölümleri kapsar.
ATILAN_BOLUMLER: tuple[str, ...] = (
    "components", "responsive", "motion & interaction", "accessibility",
    "interaction", "states", "forms", "navigation",
)

# Tuvalimizin MUTLAK çapaları — web merdivenini buraya oturtuyoruz.
# Değerler üretimden ölçüldü (1159 senaryo) ve çalışan şablonlardan:
#   manşet üst  96-132px   (25 karakter sığmalı)
#   manşet alt  60-88px    (35 karakter)
#   gövde       26-44px    (~300 karakter, auto-fit küçültür)
#   meta/etiket 22-30px
ANKARALAR: dict[str, str] = {
    "script.header_top": "96-132px",
    "script.header_bottom": "60-88px",
    "body_html": "26-44px (auto-fit küçültür, data-fit-min 24-28)",
    "meta/etiket": "22-30px",
}


@dataclass(frozen=True)
class Yon:
    """Bir tasarım dili — prompt'a hazır."""
    ad: str
    etiket: str
    ozet: str
    metin: str


def yonler(design_dir) -> list[str]:
    """Kullanılabilir dil adları (alfabetik)."""
    d = Path(design_dir)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.md")
                  if not p.stem.startswith("LICENSE"))


def _atilir(baslik: str) -> bool:
    return any(a in baslik.strip().lower() for a in ATILAN_BOLUMLER)


def _ayikla(ham: str) -> str:
    """Bize uymayan bölümleri çıkar — İKİ DÜZEYDE.

    `## Components` gibi üst düzey bölümler kadar, `## Layout` içindeki
    `### Responsive Strategy` gibi ALT bölümler de atılmalı: ilk sürüm yalnız
    `## ` bakıyordu ve responsive breakpoint tablosu prompt'ta kalıyordu.
    """
    out: list[str] = []
    atla_bolum = False       # ## düzeyi
    atla_alt = False         # ### düzeyi
    for s in ham.splitlines():
        if s.startswith("## ") and not s.startswith("### "):
            atla_bolum = _atilir(s[3:])
            atla_alt = False
        elif s.startswith("### "):
            atla_alt = _atilir(s[4:])
        if not (atla_bolum or atla_alt):
            out.append(s)
    return "\n".join(out)


def _en_buyuk_punto(metin: str) -> int:
    """Dilin merdivenindeki en büyük font boyutu (ölçek çarpanı için)."""
    puntolar = [int(float(m)) for m in re.findall(r"(\d+(?:\.\d+)?)\s*px", metin)]
    return max(puntolar) if puntolar else 0


def _capa_notu(metin: str) -> str:
    en_buyuk = _en_buyuk_punto(metin)
    carpan = round(114 / en_buyuk, 2) if en_buyuk else 0
    satir = [
        "",
        "## TUVALE OTURTMA (bu dil web için yazıldı, bizim tuvalimiz farklı)",
        "",
        "Tuval SABİT **1080 × 1920 px** dikey kart — sayfa değil, tek kare.",
        "Yukarıdaki tipografi merdiveninin ORANLARINI, karakterini ve",
        "harf aralığı işaretlerini KORU; mutlak px değerlerini KULLANMA.",
        "Merdiveni şu çapalara oturt:",
        "",
    ]
    for ad, aralik in ANKARALAR.items():
        satir.append(f"  {ad:24s} {aralik}")
    if carpan:
        satir += ["",
                  f"Kabaca ölçek: bu dilin en büyük puntosu {en_buyuk}px, "
                  f"bizim manşetimiz ~114px → yaklaşık ×{carpan}."]
    satir += [
        "",
        "Tescilli fontlar yerine dosyadaki açık kaynak karşılıklarını kullan",
        "(Google Fonts'tan `@import` ile). Manşet fontu Ç Ğ İ Ö Ş Ü",
        "göstermeli — desteklemeyen bir aileyi seçme.",
        "",
    ]
    return "\n".join(satir)


def yukle(design_dir, ad: str) -> "Yon | None":
    """Bir dili prompt'a hazır hâle getir. Yoksa None."""
    p = Path(design_dir) / f"{ad}.md"
    if not p.exists():
        return None
    ham = p.read_text(encoding="utf-8")
    ozet = ""
    m = re.search(r"^description:\s*(.+)$", ham, re.M)
    if m:
        ozet = m.group(1).strip()
    etiket = ad.replace("-", " ").title()
    m2 = re.search(r"^name:\s*(.+)$", ham, re.M)
    if m2:
        etiket = m2.group(1).strip()
    govde = _ayikla(ham)
    return Yon(ad=ad, etiket=etiket, ozet=ozet,
               metin=govde + _capa_notu(govde))


# Katalogda dil başına gösterilecek özet uzunluğu. Ölçüldü: 74 dilin ortalama
# özeti 376 karakter; 160'a kırpınca katalog ~9 KB kalıyor ve tek çağrıya rahat
# sığıyor. Tam dosyalar 2,2 MB — onlar prompt'a GİRMEZ, yalnız seçilen dilin
# tam metni girer.
OZET_KIRPMA = 160


def katalog(design_dir, adaylar=None) -> str:
    """Dillerin adı + kısa özeti — modelin SEÇEBİLMESİ için.

    `adaylar` verilirse yalnız onlar listelenir (başka kanalların kullandığı
    diller dışlanmış olarak gelir).
    """
    hepsi = yonler(design_dir)
    if adaylar is not None:
        istenen = set(adaylar)
        hepsi = [a for a in hepsi if a in istenen]
    satir = []
    for ad in hepsi:
        y = yukle(design_dir, ad)
        if y is None:
            continue
        ozet = " ".join((y.ozet or y.etiket).split())[:OZET_KIRPMA]
        satir.append(f"- {ad}: {ozet}")
    return "\n".join(satir)


def sec(design_dir, n: int, *, tohum: str, kullanilan=()) -> list[str]:
    """`n` FARKLI dil seç — aynı tohum aynı sonucu verir.

    Tohum kanal slug'ı: her kanal farklı bir üçlü alsın, ama aynı kanal için
    "yeniden üret" dediğinde sonuç tekrarlanabilir olsun.

    `kullanilan`: BAŞKA kanalların şablonlarında kullanılmış diller — önce
    bunların DIŞINDAN seçilir.

    NEDEN: konuya göre seçmek çakışmayı rastgeleden KONUSALA taşır sadece —
    iki araba kanalı da Ferrari alır (kullanıcı itirazı 2026-08-21). 74 dil,
    kanal başına 3 → hiç çakışma olmadan ~24 kanal. Havuz tükenirse yeniden
    kullanıma izin verilir; üretim durmamalı, ama bu ANCAK son çare.
    """
    hepsi = yonler(design_dir)
    if not hepsi:
        return []

    def _anahtar(ad: str) -> str:
        return hashlib.sha256(f"{tohum}:{ad}".encode("utf-8")).hexdigest()

    yasak = set(kullanilan or ())
    serbest = sorted([a for a in hepsi if a not in yasak], key=_anahtar)
    out = serbest[:max(0, n)]
    if len(out) < n:
        # Havuz tükendi: kalanı yasaklılardan tamamla (deterministik sırayla).
        kalan = sorted([a for a in hepsi if a in yasak], key=_anahtar)
        out += kalan[:n - len(out)]
    return out


def prompt_blogu(design_dir, ad: str, niyet: str) -> str:
    """Niyet + tasarım dili — tasarım prompt'una giren blok.

    Dil bulunamazsa yalnız niyet döner: kütüphane eksik diye üretim durmasın.
    """
    y = yukle(design_dir, ad)
    bas = f"İSTENEN GÖRÜNÜM: {niyet}"
    if y is None:
        return bas + "\n"
    return (
        f"{bas}\n\n"
        f"TASARIM DİLİ — bu kanalın şablonu AŞAĞIDAKİ dili konuşacak.\n"
        f"Dil: {y.etiket}\n"
        f"Özet: {y.ozet}\n\n"
        f"Dili UYGULA, kopyalama: renkleri kanalın paletiyle değiştir "
        f"(dna_css zaten geliyor), ama tipografi karakterini, boşluk "
        f"ritmini, kenar/gölge felsefesini ve yerleşim mantığını bu dilden al.\n"
        f"{y.metin}\n")
