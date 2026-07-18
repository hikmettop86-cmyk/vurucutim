"""Reel anlatım personası: few-shot örneği + ton kuralları.

Persona metni DİL PAKETİNDEN gelir (Türk dizisi referansları yalnız tr'de). Bilinmeyen
slug ya da yanlış dil RuntimeError verir — sessizce kişiliksiz'e / yanlış dile düşmek
YASAK: kullanıcı mizah seçtiyse mizah almalı, seçmediyse bugünkü davranışı almalı.
"""
from __future__ import annotations

from pydantic import BaseModel

from short_bot.lang_pack import load_pack


class Persona(BaseModel):
    slug: str
    few_shot: str
    rules: list[str]
    humor_check: bool = True


# KAPANIŞ STİLLERİ. OZAN/BEYİT TAMAMEN KALDIRILDI (kullanıcı: 'ozanı hep kaldır —
# sonunda ozan sözü saçma sapan'): zorlama kafiye anlamsız mısralar üretiyordu
# ('daha ay', 'yalan huzur'). Kapanış artık HEP kafiyesiz, GÜLDÜREN Türk sokak/mahalle
# mizahı. 'Aşık ... der ki' kalıbı HİÇBİR stilde KULLANILMAZ. seed'e göre döner
# (formülleşme kırılır — ardışık videolar farklı kapanış alır).
SIGNATURE_STYLES: list[tuple[str, str]] = [
    ("MAHALLE ÖZLÜ SÖZÜ",
     "'close' bir MAHALLE ÖZLÜ SÖZÜ / atasözü BÜKÜMÜ olsun — kısa, vurucu, sokak "
     "bilgeliği ama GÜLDÜREN bir çarpıtmayla ('Bu mahallede kural bir: ...' ya da "
     "'... eden, ... bulur.' gibi). Kafiye YOK, 'Aşık ... der ki' YOK."),
    ("RACON LAFI",
     "'close' kahramanın mikrofonu bırakırcasına attığı KISA bir RACON lafı olsun — "
     "bir-iki cümle, kabadayı ağzı, kesip atan ('Mahalle böyle bir yer koçum; anladıysan "
     "anladın.'). Kafiye YOK, 'Aşık ... der ki' YOK."),
    ("PUNCHLINE ESPRİSİ",
     "'close' seyirciyi GÜLDÜREN vurucu bir kapanış esprisi olsun — beklenmedik bir "
     "abartı ya da benzetmeyle bitir ('resmen ... gibi', 'valla ...' tadında), 'ya bu "
     "ne ya' dedirt. Kafiye YOK, ozan YOK."),
    ("İZLEYİCİYE MUHABBET",
     "'close' izleyiciye dönük sıcak, komik bir laf olsun ('sen de tanırsın böyle bir "
     "tip koçum', 'bizim mahallede de vardı böyle biri' tadında) — güldüren mahalle "
     "muhabbeti. Kafiye YOK, ozan YOK."),
]


def signature_style(seed: int) -> tuple[str, str]:
    """Bu videonun kapanış-imzası stili (etiket, talimat). seed%3 → deterministik
    rotasyon; ardışık videolar farklı stil alır (formülleşmeyi kırar)."""
    return SIGNATURE_STYLES[seed % len(SIGNATURE_STYLES)]


# --- SENARYO ÇEŞİTLEME EKSENLERİ (kullanıcı: 'senaryo hep aynı kalıp, videolar
# hep sıkıcı'). Kök neden ÖLÇÜLDÜ: prompt, açılış örneği olarak birebir 'Ula bak
# hele sahneye kardeş...' veriyordu ve iskelet sabitti → art arda 5 videonun 5'i
# de aynı cümleyle açıldı, hepsi aynı sesle anlatıldı, benzetmeler hep aynı
# dünyalardan geldi (emlakçı, kahvehane, pusu). İmza rotasyonunun kanıtlanmış
# deseni üç BAĞIMSIZ eksene genişletildi: açılış stili, anlatıcı sesi, benzetme
# dünyaları. Eksenler TUZLANMIŞ hash ile döner (reel_subscribe._idx deseni) —
# seed%N hepsini kilitleseydi 'imza=ozan olan her video aynı açılışı alır' olurdu.

HOOK_STYLES: list[tuple[str, str]] = [
    ("SAHNE DAVETİ",
     "İzleyiciyi olayın ortasına çağır — ama KENDİ sözlerinle, taze bir davetle "
     "('Şu köşedeki tipe bak', 'Gel buraya gel, bunu görmen lazım' tadında)."),
    ("UYARI / TEHDİT",
     "Hook bir mahalle uyarısı olsun: izleyiciyi bu hayvana karşı uyar "
     "('Sakın... o masum surata kanma', 'Bu tiple asla dalaşma' tadında)."),
    ("TERS KÖŞE TANITIM",
     "Önce masum/sıradan tanıt, aynı cümlede tersine çevir ('Şu uyuşuk amca var ya... "
     "mahallenin en tehlikeli adamı o.' tadında). Kontrast ne sert, o kadar iyi."),
    ("OLAYIN ORTASINDAN",
     "Hook olayın TAM ORTASINDAN, aksiyonla açılsın — takdim yok, patlama var "
     "('Kobra yere serildi. Evet, kobra. Seren adam da şu ufaklık.' tadında)."),
    ("DEDİKODU / SON DAKİKA",
     "Mahalleye haber getirir gibi aç ('Duydun mu, aşağı mahallede olay çıkmış...', "
     "'Son dakika koçum: ...' tadında) — sıcak bir kulis bilgisi verir gibi."),
    ("İZLEYİCİYE RACON SORUSU",
     "İzleyiciye meydan okuyan bir racon sorusuyla aç ('Sen olsan bu adama bulaşır "
     "mıydın?', 'Karşında böylesi olsa ne yapardın?' tadında). Bilgi sorusu DEĞİL "
     "('biliyor muydunuz' yine yasak) — cesaret/racon sorusu."),
]

FRAME_STYLES: list[tuple[str, str]] = [
    ("CANLI MAÇ SPİKERİ",
     "Olayı saha kenarından, maç heyecanıyla nakleden spiker sesi — tempo yüksek, "
     "goller/fauller anons edilir gibi."),
    ("BELGESEL PARODİSİ",
     "Belgesel anlatıcısını mahalle ağzıyla taklit et — 'doğanın bu asil evladı' "
     "diye başlayıp 'ama bizimki resmen zorba çıktı' diye bozulan ciddiyetsiz ses."),
    ("OLAY YERİ MUHABİRİ",
     "Olay yerinden canlı bağlanan muhabir sesi — 'şu an arkamda gördüğünüz...' "
     "tadında, kameramana laf atan, yayını koparmayan telaşlı canlılık."),
    ("KAHVEHANE ANLATICISI",
     "Kahvehane masasından olayı BİZZAT GÖRMÜŞ adamın ağzı — 'vallahi gözümle "
     "gördüm' enerjisi, dinleyenleri masaya toplayan abartılı tanıklık. Olayı yine "
     "ŞİMDİKİ zamanda canlandır ('bak şimdi şöyle yapıyor...')."),
    ("ESNAF GEZDİRMESİ",
     "Müşteriye mal/mahal gezdiren esnaf ağzı — hayvanı ve arazisini 'buyur abi, "
     "şu tarafta da...' diye sunar, öve öve bitiremez ama araya dobra uyarılar "
     "sıkıştırır ('yalnız şununla göz göze gelme')."),
    ("DEDİKODUCU KOMŞU",
     "Balkondan balkona dedikodu veren komşu sesi — 'kızım duydun mu', 'ay ben "
     "bunu hep diyordum' tadında, olayları içeriden bilen keyifli fısıltı ama "
     "sahne yine gözünün önünde AKAR."),
]

# Benzetme dünyaları havuzu: her videoya İKİ farklı dünya seçilir, gerisi o video
# için kapanır. Böylece 'her videoda emlakçı + kahvehane' tekrarı kırılır.
METAPHOR_DOMAINS: list[str] = [
    "otomotiv/sanayi (Tofaş, usta-çırak, vites, egzoz)",
    "esnaf/pazar (pazarcı, manav, veresiye defteri)",
    "futbol/maç (hakem, ofsayt, 90+3, taraftar)",
    "devlet dairesi/bürokrasi (evrak, sıra numarası, mesai)",
    "düğün/eğlence (davul-zurna, takı töreni, halay başı)",
    "eski Türk dizileri/filmleri (Kurtlar Vadisi, Çukur, Yeşilçam raconu)",
    "apartman/site yönetimi (aidat, yönetici, asansör arızası)",
    "dolmuş/trafik (şoför, 'inecek var', makas atmak)",
    "kahvehane/okey (taş, çay ocağı, kâğıt oyunu)",
    "berber/kuaför (ustura, saç-sakal, ayna)",
    "spor salonu/boks (ring, antrenör, ağır sıklet)",
    "ekonomi/kira-zam (enflasyon, kira artışı, pazarlık)",
]


def _rot(seed: int, salt: str, n: int) -> int:
    """Tuzlanmış deterministik eksen seçimi (reel_subscribe._idx deseni)."""
    import hashlib
    h = hashlib.sha1(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return int(h, 16) % n


def hook_style(seed: int) -> tuple[str, str]:
    """Bu videonun AÇILIŞ stili (etiket, talimat) — imzadan bağımsız döner."""
    return HOOK_STYLES[_rot(seed, "hook", len(HOOK_STYLES))]


def frame_style(seed: int) -> tuple[str, str]:
    """Bu videonun ANLATICI SESİ (etiket, talimat) — diğer eksenlerden bağımsız."""
    return FRAME_STYLES[_rot(seed, "frame", len(FRAME_STYLES))]


def metaphor_domains(seed: int) -> tuple[str, str]:
    """Bu videonun İKİ benzetme dünyası — birbirinden farklı, videolar arası döner."""
    n = len(METAPHOR_DOMAINS)
    i = _rot(seed, "dom1", n)
    j = _rot(seed, "dom2", n - 1)
    if j >= i:
        j += 1                      # ikinci dünya birinciden HEP farklı
    return METAPHOR_DOMAINS[i], METAPHOR_DOMAINS[j]


def load_persona(slug: str, *, language: str) -> Persona | None:
    if not (slug or "").strip():
        return None                      # kişiliksiz: bugünkü prompt, sıfır regresyon
    pack = load_pack(language)
    data = (pack.personas or {}).get(slug)
    if not data:
        raise RuntimeError(
            f"persona '{slug}' {language} dil paketinde yok — "
            f"bu persona bu dilde tanımlı değil (sessiz düşme yok)")
    return Persona(slug=slug, few_shot=data.get("few_shot", ""),
                   rules=list(data.get("rules", [])),
                   humor_check=bool(data.get("humor_check", True)))


def mascot_block(name: str, animal: str, trait: str) -> str:
    """Senaryo prompt'una eklenecek MASKOT (tekrar eden ana karakter) bloğu.

    Üçü de doluysa maskot aktif; biri boşsa "" (maskot yok, her video bağımsız).
    Maskot persona'dan AYRI: persona TON (mahalle ağzı), maskot KARAKTER (Deli Kâzım).
    """
    if not all((name or "").strip() and (x or "").strip() for x in (name, animal, trait)):
        return ""
    return (
        f"=== ANA KARAKTER (MASKOT — KANALIN YÜZÜ) ===\n"
        f"Bu kanalın SABİT baş karakteri: {name} ({animal}). Kişilik: {trait}.\n"
        f"Her videoda AYNI isim, AYNI kişilik — izleyici {name}'ı tanısın ve ona "
        f"bağlansın (bir videoya değil, KARAKTERE abone olsun).\n"
        f"KONU {animal.upper()} İLE İLGİLİYSE: {name}'ı doğrudan merkeze al, onun bir "
        f"macerası/özelliği gibi anlat.\n"
        f"KONU BAŞKA BİR HAYVANSA: {name} onu kendi mahalle-abisi gözünden YORUMLAR/"
        f"KIYASLAR — o hayvanın yanına gitmez (coğrafi tutarlılık). Örnek: 'bu penguen "
        f"çakıl çalıyormuş; bizim {name} görse taşı da alırdı sahibini de'.\n"
        f"Manşet ve kapanış imzası {name}'ın ismini taşıyabilir (imza stili döner: "
        f"mahalle özlü sözü / racon lafı / güldüren punchline — sana bu videonunki verilir).\n")


def topic_guidance(persona: Persona | None) -> str:
    """Konu üretimine verilecek niş-üstü yönerge (propose_topics.extra_guidance).

    Mizah kanalı için konu SEÇİMİ mizahı hedeflemeli: DiscoverNow'un en çok tutan
    videoları hep KARAKTERLİ/KABADAYI hayvanlar (bal porsuğu, kangal, leopar). Konu
    üretimi persona-agnostik olduğu için hüzünlü/nötr davranışlar da geliyordu
    (fil hafızası, göç). Bu yönerge üretimi karakterli davranışlara çeker.
    """
    if persona is None or persona.slug != "vahsi_mizah":
        return ""
    return (
        "MİZAH KANALI — KONU SEÇİMİ ÖNEMLİ: Bu kanal hayvanları bir MAHALLE "
        "KARAKTERİNE büründürüp komik anlatıyor. O yüzden KARAKTERLİ, KABADAYI, "
        "TUHAF, KURNAZ ya da KOMİK davranışlı hayvan/olayları TERCİH ET — korkusuzluk, "
        "kavga, blöf, kıskançlık, kurnazlık, hiyerarşi, tuhaf çiftleşme/yavru bakımı "
        "gibi 'mahalle tipi' davranışlar. Örnek uygun: bal porsuğunun cesareti, "
        "ahtapotun komşusuna çamur fırlatması, capuchin'in adalet duygusu, sincabın "
        "sahte çukur kazması, kanganın boks yapması. KAÇIN: hüzünlü/nötr/duygusal "
        "olgular (fil hafızası, göç mesafeleri, nesli tükenme) — bunlar komik "
        "anlatıma DİRENÇLİDİR. Her konu, hayvanın bir 'karakterini' ortaya koymalı.\n"
        "GÖRSEL + HAREKETLİ OLMALI (EN ÖNEMLİ — kullanıcı geri bildirimi): Bu videolar "
        "STOK FOOTAGE üstüne anlatılır. Konu, stok kütüphanenin GERÇEKTEN gösterebileceği, "
        "hayvanın BEDENİYLE yaptığı, kamerada HAREKET olan bir eylem olmalı: KOVALAMACA, "
        "SALDIRI, KAVGA, KOŞU, AVLANMA, sıçrama, yüzme, tırmanma, güç gösterisi. İKİ AYRI "
        "TUZAK VAR, ikisinden de kaçın:\n"
        "  (1) GÖRÜNMEZ mikro-detay: 'susamuru favori taşını CEBİNDE saklar', 'tilki "
        "KUZEYE bakarak avlanır', 'balık deniz tabanına MOTİF çizer'. İzleyici o "
        "taşı/yönü/motifi GÖREMEZ (sadece 'hayvan yüzüyor' görür) → 'anlatılan bu değil' "
        "deyip kopar.\n"
        "  (2) HAREKETSİZ eylem: 'timsah saatlerce PUSUDA bekler', 'ahtapot KAMUFLAJ "
        "yapıp durur', 'hayvan UYUR/donar'. Footage'ın tamamı kıpırtısız olur → video "
        "DONUK görünür, kapanışta 'donmuş kuyruk' oluşur (ÖLÇÜLDÜ: timsah pusu videosu "
        "son 8sn %84 donuk). Durgun-ama-ilginç bir davranışı bile HAREKETLİ ANIYLA seç: "
        "'timsah pusu' YERİNE 'timsahın sudan ANİ FIRLAYIP avı kapması'.\n"
        "TEST: 'Bu olayı Pexels'te aratsam, hayvan HAREKET HÂLİNDE mi çıkar?' Durgun "
        "çıkıyorsa (yatıyor/bekliyor/yüzüyor) o konuyu ALMA — hareketli bir eylem seç.\n"
        "TÜR ADI GENEL OLSUN: 'Adélie pengueni' / 'kea papağanı' gibi SPESİFİK "
        "alt-tür yerine GENEL adı kullan ('penguen', 'papağan'). Stok görüntü "
        "spesifik alt-türü bulamayıp yanlış tür getiriyor (Adélie konusu → sarı-kaşlı "
        "rockhopper görüntüsü) ve izleyici 'anlatılan bu değil' diye kopuyor. "
        "Mizahta önemli olan hayvanın KARAKTERİ, alt-türü değil.")


def director_guidance(persona: Persona | None) -> str:
    """Kurgucuya (reel_director) verilecek yönerge. Mizah videosu EĞLENCELİ
    kurgulanmalı — kurgucu persona-agnostik olduğu için mizah anlatımına 'dark/tense'
    mood + gerilim müziği seçebiliyordu (ölçüldü: short 813, mood=dark/glitch/tense).
    """
    if persona is None or persona.slug != "vahsi_mizah":
        return ""
    return (
        "BU BİR MİZAH VİDEOSU (hayvan mahalle karakterine bürünmüş, komik anlatım). "
        "Kurgu EĞLENCELİ ve TEMPOLU olmalı: mood 'upbeat' seç (mizahta 'dark'/'tense' "
        "YANLIŞTIR — ciddi/gerilim tonu komediyi öldürür). Müzik neşeli/enerjik olsun. "
        "SFX'ler canlı ve vurucu — komik anları (blöf, kavga, twist) 'impact'/canlı "
        "kategoriyle noktala. Amaç: izleyici gülümserken izlesin, gerilmesin.")


def channel_director_guidance(persona_slug: str, language: str) -> str:
    """Kanal persona slug'ından kurgu rehberi (güvenli sarmalayıcı, bkz. topic sürümü)."""
    if not (persona_slug or "").strip():
        return ""
    try:
        p = load_persona(persona_slug, language=language)
    except RuntimeError:
        return ""
    return director_guidance(p)


def channel_topic_guidance(persona_slug: str, language: str) -> str:
    """Kanal persona slug'ından konu üretim rehberi. Güvenli sarmalayıcı:
    boş slug ya da yanlış dil → "" (konu üretimi bozulmaz, sadece mizah-agnostik olur).
    refresh_topic_bank'in tüm çağıranları bunu ``extra_guidance`` olarak geçirir."""
    if not (persona_slug or "").strip():
        return ""
    try:
        p = load_persona(persona_slug, language=language)
    except RuntimeError:
        return ""
    return topic_guidance(p)


def persona_block(persona: Persona, *, seed: int = 0) -> str:
    kurallar = "\n".join(f"{i+1}. {r}" for i, r in enumerate(persona.rules))
    imza_etiket, imza_talimat = signature_style(seed)
    acilis_etiket, acilis_talimat = hook_style(seed)
    ses_etiket, ses_talimat = frame_style(seed)
    dunya1, dunya2 = metaphor_domains(seed)
    return (
        "=== ANLATIM PERSONASI + SAHNE MODU (EN ÖNEMLİ KATMAN — YUKARIDAKİ YAPIYI EZER) ===\n"
        "DİKKAT: Yukarıda 'ilginç bilgi arkı' (hook→en şok edici BİLGİ→twist) anlatıldı.\n"
        "PERSONA MODUNDA O YAPI YERİNE ŞU GEÇER — bu bir BİLGİ videosu DEĞİL, bir SAHNE.\n"
        "Sen sahada CANLI MAÇ ANLATICISISIN: bir hayvan ŞU AN, gözünün önünde bir olay\n"
        "yaşıyor; sen onu racon keserek, kahkaha attırarak naklediyorsun. Ölçtük: bizim\n"
        "en büyük eksik, çıktının 'mizahi anlatılmış bir bilgi kartı' olması — oysa\n"
        "referans kanal SAHNELENMİŞ bir mahalle olayı anlatıyor. Fark BURADA kapanır.\n\n"
        f"TON ÖRNEĞİ (aynen bu tadda yaz — mahalle ağzı, canlı, komik):\n---\n"
        f"{persona.few_shot}\n---\n\n"
        "SAHNENİN İSKELETİ (fact-arc DEĞİL, scene-arc — beat'leri buna göre kur):\n"
        "  • AÇILIŞ (hook): bu videonun AÇILIŞ STİLİ aşağıdaki ÇEŞİTLEME REÇETESİNDE\n"
        "    verilir — ona uy. 'Biliyor muydunuz' KESİN YASAK (bilgi tonu sahneyi\n"
        "    öldürür). 'Ula bak hele sahneye' KALIBI DA YASAK: art arda 5 video bu\n"
        "    cümleyle açıldı, formül ele verdi — her video KENDİ sözleriyle açılır.\n"
        "  • KURULUM: hayvanı bir mahalle karakteri olarak sahneye koy (lakap + kimlik),\n"
        "    ortamı kur.\n"
        "  • OLAY / ÇATIŞMA: bir ŞEY OLUR — rakip çıkar, tehdit gelir, meydan okunur.\n"
        "    Mümkünse KARŞI KARAKTER (rakip hayvan/tehdit) de sahnede olsun ve iki\n"
        "    karakter ATIŞSIN. Çatışma yoksa hayvanın 'olayı' sahnelensin (kurnazlık,\n"
        "    blöf, gösteri) — yine bir AN olarak, ders olarak değil.\n"
        "  • TEPE (peak_beat) = en çarpıcı AN, bir BİLGİ değil bir DÖNÜŞ: ters köşe.\n"
        "  • RACON + KAPANIŞ: kahraman racon keser/kazanır → mahalle imzası (stil aşağıda).\n\n"
        "=== BU VİDEONUN ÇEŞİTLEME REÇETESİ (formül kırıcı — HER VİDEO FARKLI) ===\n"
        "Aynı kanalın videoları art arda izlenir; açılış/ses/benzetme tekrarı anında\n"
        "sırıtır. Bu videoya ÖZEL seçimler (SONRAKİ videolar farklısını alacak):\n"
        f"  • AÇILIŞ STİLİ → {acilis_etiket}: {acilis_talimat}\n"
        "    (Örnek sözleri AYNEN kopyalama — stilin RUHUNU al, cümleyi kendin kur.)\n"
        f"  • ANLATICI SESİ → {ses_etiket}: {ses_talimat}\n"
        "    (Hangi ses olursa olsun: şimdiki zaman, canlı sahne, mahalle sıcaklığı.)\n"
        f"  • BENZETME DÜNYALARI (çeşitlilik dürtüsü, ZORUNLULUK DEĞİL) → benzetme\n"
        f"    YAPACAKSAN tekrar-kırmak için ağırlıkla şu iki dünyadan seç:\n"
        f"    (1) {dunya1}  (2) {dunya2}. AMA sahneye UYMAYAN dünyayı ASLA dayatma:\n"
        "    uymayan metafor (örn. alçak uçan uçağa 'kira zammı', denizle alakasız\n"
        "    'davulla köye') espriyi ÖLDÜRÜR ve YAPAY durur. O zaman o dünyayı AT,\n"
        "    esprin GERÇEK sahnede olup bitenden çıksın — apt (yerini bulan) sahne\n"
        "    mizahı, zorlanmış benzetmeyi HER ZAMAN yener. Uyuyorsa kullan, uymuyorsa\n"
        "    metaforsuz kal. Emlakçı/kahvehane klişesine de girme.\n"
        "  • HİTAP DOZU: 'bizimki' EN FAZLA 2 kez — yerine isim/lakap ve dönen\n"
        "    hitaplar kullan (kardeş, koçum, reis, usta, gardaş, kaptan...).\n\n"
        "SEMPATİK VE SICAK OL (EN ÖNEMLİSİ — kullanıcı geri bildirimi): karakter\n"
        "SEVİLESİ olmalı, mesafeli/resmi değil. Güleryüzlü bir mahalle abisi anlatıyor:\n"
        "hayvana sevgiyle takılır, insani zaafları olan bir tip gibi sunar ('bizimki',\n"
        "'garibim', 'koçum'). RESMİ/BELGESEL/TEKNİK KELİME YASAK — bunlar yapay-zekâ\n"
        "kokar ve sıcaklığı öldürür: 'disiplin abidesi', 'etkisiz hale getirmek',\n"
        "'tecrübe transferi', 'bünye', '... modunda', 'söz konusu', 'gerçekleştiriyor'.\n"
        "Bunların yerine sokak ağzı: 'işi biliyor', 'temizliyor', 'gösteriyor işte'.\n\n"
        "SAHNEYİ CANLI TUTAN ARAÇLAR — ama ÇEŞİTLİ KULLAN (formül = yapay):\n"
        "  • ŞİMDİKİ ZAMAN, CANLI: 'fırlıyor', 'çakıyor', 'yere seriliyor'. Olay ŞU AN\n"
        "    oluyor. Geçmiş zaman ve bilgi tonu ('bilinir ki', 'aslında') sahneyi öldürür.\n"
        "  • ARAÇ KUTUSU — bunları KARIŞTIR, arka arkaya AYNISINI kullanma:\n"
        "      (a) 'sanırsın X' benzetmesi   (b) kısa patlama cümle ('Kobra şokta. Kobra\n"
        "      iptal.', 'Yürüyüşe bak.')   (c) diyalog/iç ses   (d) izleyiciye seslenme\n"
        "      ('yok artık kardeş', 'gördün mü şunu')   (e) absürt abartı ('mezara değil paralel\n"
        "      evrene fırlatır').\n"
        "    RİTİM DEĞİŞSİN: uzun bir cümlenin ardından kısa bir patlama gelsin.\n"
        "  • 'SANIRSIN' TUZAĞI (824 hatası — kullanıcı fark etti): benzetmeyi HER cümleye\n"
        "    tıkıştırma, bir kalıp değildir. Bir sahnede EN FAZLA 3-4 benzetme, ARALARINDA\n"
        "    başka araç olsun. VE HER BENZETME BAMBAŞKA DÜNYADAN: biri otomotiv, biri\n"
        "    esnaf, biri futbol, biri eski dizi, biri devlet dairesi — ASLA üç benzetme\n"
        "    aynı temadan ('hepsi usta-çırak' gibi). Aynı kalıbı tekrarlarsan formül ele\n"
        "    verir, video YAPAY durur. Beklenmedik, çeşitli, tahmin edilemez ol.\n"
        "  • DİYALOG / ATIŞMA: hayvana AĞIZ ver — iç konuşma ya da karşı karakterle laf\n"
        "    dalaşı ('Sen hâlâ burada mısın sinsi hortum?'). En az bir replik olsun\n"
        "    (TEK tırnak — çift tırnak JSON'u bozar).\n"
        "  • Gerçek bilgi sahnenin İÇİNE gömülür — ders gibi değil, olayın bir ANI gibi.\n"
        "  • GÖRSEL SADAKAT (kullanıcı geri bildirimi — iki ayrı kusur ölçüldü):\n"
        "    (a) GÖRÜNMEYEN ayrıntı: ekranda görünmeyen küçük nesneyi ('koltuk altındaki\n"
        "        taş', 'mikroskobik salgı') sahnenin OMURGASI yapma — izleyici göremez,\n"
        "        'anlatılan bu değil' der. Değinip geç, üstüne kurma.\n"
        "    (b) İKİNCİL ÖZNE: senaryoda GÖRÜNÜR rol oynayan İKİNCİ hayvan (av, rakip,\n"
        "        düşman) EN AZ BİR beat'te ekranda görünmeli. 'gepar CEYLANI kovalıyor'\n"
        "        diyorsan bir beat'in visual_query'si 'gazelle running' olsun — yoksa\n"
        "        izleyici sadece gepar görür, ceylanı hiç görmez (ÖLÇÜLDÜ: gepar videosu,\n"
        "        ceylandan bahsedip hiç göstermedi). İki özneli sahne = iki öznenin de\n"
        "        footage'ı.\n"
        "    (c) EYLEMİ İSTE: visual_query'ler durgun tür-portresi DEĞİL, EYLEM göstersin:\n"
        "        'cheetah running / cheetah hunting', 'lion charging', 'eagle diving' —\n"
        "        'cheetah' tek başına durup duran hayvan getirir (ÖLÇÜLDÜ: gepar koşmadı,\n"
        "        yürüdü). Aksiyon query'si hem sahneyi canlandırır hem donuk kareyi azaltır.\n"
        "    (d) OLAY YÖNÜNÜ TERS ÇEVİRME: iki hayvan çatışmasında stok footage DOĞADAKİ\n"
        "        sonucu gösterir (avcı avı yakalar). Senaryo footage'ın GÖSTEREMEYECEĞİ bir\n"
        "        SONUÇ/GALİP iddia etmesin: 'zebra aslanı yendi, kral yerle bir' derken\n"
        "        ekranda aslan zebrayı yiyor (ÖLÇÜLDÜ, short 833) → izleyici tersini görür,\n"
        "        güven gider. Kahramanın GÜCÜNÜ/CESARETİNİ/tehlikesini/kaçışını anlat ama\n"
        "        KESİN ters-galibiyet UYDURMA. Aşırı kanlı av-yeme sahnesi de mizah tonunu\n"
        "        bozar — 'kovalama/kaçış/meydan okuma' anını seç, 'parçalama' anını değil.\n\n"
        f"KURALLAR (hepsi ZORUNLU):\n{kurallar}\n\n"
        "MİZAH SIKIŞTIRILAMAZ: kelimeleri kısıp esprisiz özet çıkarma. Nefes alanı "
        "olan, kurulup boşalan şakalar yaz. Her beat bir sahne/espri taşısın; boş "
        "geçiş cümlesi ('işin sırrı burada', 'bak şimdi') YOK — o saniyeyi de bir\n"
        "benzetme ya da replikle doldur.\n\n"
        "ÇIKTI DİSİPLİNİ (JSON BOZULMASIN): Senaryo metinlerinde (hook, beat, close, "
        "comment) ASLA çift tırnak (\") kullanma — diyalog/alıntı için TEK tırnak (') "
        "kullan. Örnek: karga 'kırmızı tişörtlü cimrinin teki geçti' der. Yanıt "
        "SADECE geçerli JSON olsun, markdown kod bloğu ekleme.\n\n"
        "KAPANIŞ (close) = MAHALLE İMZASI, ZORUNLU (kanalın markası — atlanamaz). Her\n"
        "video bir imzayla biter AMA STİL DÖNER (hep aynı kalıp = formül, yapay\n"
        f"durur). BU VİDEONUN İMZA STİLİ → {imza_etiket}: {imza_talimat}\n"
        "HANGİ STİL OLURSA OLSUN: 'close' EN FAZLA 120 KARAKTER, hook'un bir sözcüğünü\n"
        "içersin (loop callback), düz özet cümlesi ('işte bu yüzden ... gibisi yok')\n"
        "imza SAYILMAZ. Kapanış HEP kafiyesiz, güldüren mahalle mizahı — 'Aşık ... der ki'\n"
        "ya da ozan beyti YAZMA (kafiye zorlaması saçma çıkıyor). Yorum sorusunu close'a\n"
        "KOYMA, 'comment' alanına yaz.\n")
