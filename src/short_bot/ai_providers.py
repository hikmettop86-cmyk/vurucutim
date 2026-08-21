"""AI sağlayıcı kaydı — hangi model nereden çağrılır.

NEDEN TEK KAYIT: sağlayıcı bilgisi (uç nokta, anahtar adı, örnek modeller)
eskiden `config.resolve_ai_call` içine, `claude_cli._invoke_primary` içine ve
ayarlar şablonuna DAĞILMIŞTI. Yeni bir sağlayıcı eklemek üç yeri birden
düzenlemek demekti ve biri unutulunca sessizce eski sağlayıcıya düşülüyordu.

ÖLÇÜLDÜ (2026-08-21, arketip şablonu yazma görevi — 33 KB prompt, ~6-10 KB
HTML çıktı; hepsi yapı kapısından geçti):

    claude_cli / opus                        112,7 sn   (Max planı, ücretsiz)
    google_studio / gemini-3.5-flash-lite      7,0 sn   (ÜCRETSİZ havuz)
    google_studio / gemini-3.1-flash-lite      6,9 sn   (ÜCRETSİZ havuz)
    openrouter / google/gemini-3.5-flash-lite  6,3 sn
    deepseek / deepseek-chat                  13,2 sn
    qwen / qwen3-coder-plus                   30,1 sn

Yani Claude CLI'nin 112 saniyesi modelden değil CLI'nin kendisinden geliyor;
aynı işi ücretsiz havuz 16 kat hızlı yapıyor. KALİTE AYNI DEĞİL: Opus'un
şablonunda manşet satırları ayrıydı, flash-lite'ta üst üste bindi (vision
kapısı geçirdi ama göz farkı görüyor). Bu yüzden seçim AYARLARDA duruyor,
kodda sabitlenmiyor.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Saglayici:
    """Bir AI sağlayıcısı.

    `base_url` doluysa OpenAI-uyumlu `/chat/completions` konuşur ve tek bir
    istemci (`openai_compat`) yeter. Boşsa özel yolu vardır (Claude CLI
    subprocess, Google Studio havuzu, OpenRouter'ın kendi istemcisi).
    """
    ad: str
    etiket: str
    base_url: str = ""
    gizli_anahtar: str = ""          # secrets.yaml'daki alan adı
    ornek_modeller: tuple[str, ...] = ()
    gorsel: bool = False             # görsel (vision) çağrısı destekliyor mu
    ucretsiz: bool = False
    not_: str = ""


# Özel yolu olanlar (base_url yok) + OpenAI-uyumlu olanlar tek listede.
SAGLAYICILAR: dict[str, Saglayici] = {
    "claude_cli": Saglayici(
        ad="claude_cli", etiket="Claude CLI (abonelik)",
        ornek_modeller=("opus", "sonnet", "haiku"), gorsel=True, ucretsiz=True,
        not_="Max planına dahil, token ücreti yok — ama her çağrı yeni süreç: "
             "ölçüldü 112,7 sn (aynı işi ücretsiz Google havuzu 7 sn'de yapıyor)."),
    "google_studio": Saglayici(
        ad="google_studio", etiket="Google AI Studio (ücretsiz havuz)",
        ornek_modeller=("gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                        "gemma-4-26b-a4b-it"),
        gorsel=True, ucretsiz=True,
        not_="data/google_pool/google-keys.json içindeki anahtarlar sırayla "
             "kullanılır (500/gün/anahtar). Tükenirse OpenRouter'a düşer."),
    "openrouter": Saglayici(
        ad="openrouter", etiket="OpenRouter", gizli_anahtar="openrouter_api_key",
        ornek_modeller=("google/gemini-3.5-flash-lite", "anthropic/claude-sonnet-5",
                        "deepseek/deepseek-chat", "qwen/qwen3-coder",
                        "google/gemma-4-26b-a4b-it"),
        gorsel=True,
        not_="Tek anahtarla yüzlerce modele erişir; sağlayıcıların kendi "
             "API'lerinden biraz pahalı ama tek yerden yönetilir."),
    "deepseek": Saglayici(
        ad="deepseek", etiket="DeepSeek",
        base_url="https://api.deepseek.com/chat/completions",
        gizli_anahtar="deepseek_api_key",
        ornek_modeller=("deepseek-chat", "deepseek-reasoner"),
        not_="Ölçüldü: şablon yazma 13,2 sn."),
    "qwen": Saglayici(
        ad="qwen", etiket="Qwen (DashScope)",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        gizli_anahtar="qwen_api_key",
        ornek_modeller=("qwen3-coder-plus", "qwen3-max", "qwen3-vl-plus"),
        gorsel=True, not_="Ölçüldü: şablon yazma 30,1 sn."),
    "openai": Saglayici(
        ad="openai", etiket="OpenAI",
        base_url="https://api.openai.com/v1/chat/completions",
        gizli_anahtar="openai_api_key",
        ornek_modeller=("gpt-5.2", "gpt-5.2-mini"), gorsel=True),
    "gemini_direct": Saglayici(
        ad="gemini_direct", etiket="Google Gemini (tek anahtar)",
        gizli_anahtar="gemini_api_key",
        ornek_modeller=("gemini-3.5-flash-lite", "gemini-3.5-pro"),
        gorsel=True,
        not_="Tek anahtar. Ücretsiz havuz (google_studio) varken gereksiz; "
             "havuz tükendiğinde yedek olarak işe yarar."),
    "modelscope": Saglayici(
        ad="modelscope", etiket="ModelScope",
        base_url="https://api-inference.modelscope.ai/v1/chat/completions",
        gizli_anahtar="modelscope_api_key",
        ornek_modeller=("Qwen/Qwen3-VL-30B-A3B-Instruct",),
        gorsel=True, not_="Günde 500/model ücretsiz kota."),
    "groq": Saglayici(
        ad="groq", etiket="Groq",
        base_url="https://api.groq.com/openai/v1/chat/completions",
        gizli_anahtar="groq_api_key",
        ornek_modeller=("llama-4-70b", "qwen3-32b")),
    "nvidia": Saglayici(
        ad="nvidia", etiket="NVIDIA NIM",
        base_url="https://integrate.api.nvidia.com/v1/chat/completions",
        gizli_anahtar="nvidia_api_key",
        ornek_modeller=("deepseek-ai/deepseek-v3.2",)),
}

# Rol başına sağlayıcı seçilebilir. Roller `config.resolve_ai_call` ile aynı.
ROLLER: tuple[tuple[str, str], ...] = (
    ("dna", "Görsel kimlik / arketip tasarımı"),
    ("script", "Senaryo ve sohbet"),
    ("default", "Genel (skorlama, başlık, yardımcı işler)"),
    ("vision", "Görsel denetim (render karesine bakma)"),
)


def saglayici(ad: str) -> Saglayici | None:
    return SAGLAYICILAR.get(ad)


def openai_uyumlu(ad: str) -> bool:
    s = SAGLAYICILAR.get(ad)
    return bool(s and s.base_url)


def gorsel_saglayicilar() -> list[str]:
    return [a for a, s in SAGLAYICILAR.items() if s.gorsel]


def gerekli_anahtar(ad: str) -> str:
    s = SAGLAYICILAR.get(ad)
    return s.gizli_anahtar if s else ""
