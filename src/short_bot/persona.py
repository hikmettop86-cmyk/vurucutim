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
        f"Manşet ve ozan imzası {name}'ın ismini taşıyabilir ('Aşık {name} der ki...').\n")


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


def persona_block(persona: Persona) -> str:
    kurallar = "\n".join(f"{i+1}. {r}" for i, r in enumerate(persona.rules))
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
        "  • AÇILIŞ (hook) = SAHNEYE DAVET, bilgi sorusu DEĞİL. İzleyiciyi olayın\n"
        "    ortasına at: 'Ula bak hele sahneye kardeş...', 'Sakın ama sakın ...'.\n"
        "    'Biliyor muydunuz' KESİN YASAK — o bilgi tonudur, sahneyi öldürür.\n"
        "  • KURULUM: hayvanı bir mahalle karakteri olarak sahneye koy (lakap + kimlik),\n"
        "    ortamı kur.\n"
        "  • OLAY / ÇATIŞMA: bir ŞEY OLUR — rakip çıkar, tehdit gelir, meydan okunur.\n"
        "    Mümkünse KARŞI KARAKTER (rakip hayvan/tehdit) de sahnede olsun ve iki\n"
        "    karakter ATIŞSIN. Çatışma yoksa hayvanın 'olayı' sahnelensin (kurnazlık,\n"
        "    blöf, gösteri) — yine bir AN olarak, ders olarak değil.\n"
        "  • TEPE (peak_beat) = en çarpıcı AN, bir BİLGİ değil bir DÖNÜŞ: ters köşe.\n"
        "  • RACON + KAPANIŞ: kahraman racon keser/kazanır → ozan imzası.\n\n"
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
        "      ('bak hele', 'yok artık kardeş')   (e) absürt abartı ('mezara değil paralel\n"
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
        "KAPANIŞ (close) = OZAN İMZASI, ZORUNLU (kanalın markası — atlanamaz): 'close'\n"
        "alanı MUTLAKA 'Aşık [Hayvan/İsim] der ki:' ile başlayan, KAFİYELİ 2 mısralık\n"
        "halk-ozanı kapanışı olmalı ve hook'un bir sözcüğünü içermeli (loop callback).\n"
        "EN FAZLA 120 KARAKTER. Düz bir özet cümlesi ('işte bu yüzden ... gibisi yok')\n"
        "KAPANIŞ DEĞİLDİR — o ozan imzasının yerini ALAMAZ. Yorum sorusunu close'a KOYMA,\n"
        "'comment' alanına yaz.\n")
