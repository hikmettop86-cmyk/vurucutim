"""Kapı merdiveni + red-hafızası + gerçek exclude.

GERÇEK KOŞU (And Kondoru, short_id=742) logu üç kusuru birden gösterdi:

1. exclude ÇALIŞMIYORDU: match_beat_clip onu ADAY URL'sine karşı denetliyordu
   (``c.url in exclude``) ama reel.py ona KLİP DOSYA YOLLARI gönderiyordu. Sonuç:
   her segment aynı klibi yeniden buluyor, çağıran ``clip in got`` görüp döngüyü
   kırıyordu → her segmentte 1 klip.
2. REDDEDİLEN ADAYLAR HER YUVA İÇİN BAŞTAN YARGILANIYORDU: 67 vision çağrısının
   çoğu aynı martı/pelikan/kelebek/kartal döngüsüydü. Bütçe (10 kapı) tükeniyor,
   yeni adaylara hiç sıra gelmiyordu.
3. KAPI FAZLA KATIYDI: "kanatlarını açmış kartal" bir kondor videosu için
   mükemmel b-roll'dü, reddedildi → vision'sız son çare devreye girdi ve karlı
   dağda YÜRÜYEN BİR İNSAN geldi. Doğrulanmamış çöp, gevşek-kapılı b-roll'den
   çok daha kötü.
"""
from pathlib import Path

from short_bot.footage_matcher import (FootageDeps, _seen_key,
                                       download_banked, match_beat_clip)
from short_bot.footage_sources import FootageCandidate


class _V:
    """Sahte vision yargısı (gerçek _FootageVerdict ile aynı alanlar)."""
    def __init__(self, matches, in_context, clear):
        self.matches, self.in_context, self.clear = matches, in_context, clear
        self.content, self.reason = "", ""


class _Src:
    name = "stub"

    def __init__(self, cands, calls):
        self._cands = cands
        self._calls = calls

    def available(self):
        return True

    def search(self, q, *, max_results, orientation):
        # portrait+landscape iki kez sorulur; aynı listeyi döndür
        return self._cands

    def download(self, cand, cache_dir):
        self._calls["download"].append(cand.url)
        p = Path(cache_dir) / cand.url.split("/")[-1]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"mp4")
        return p


def _cands(*names):
    return [FootageCandidate(url=f"https://x/{n}.mp4", image=f"https://x/{n}.jpg",
                             duration_s=10) for n in names]


def test_exclude_matches_downloaded_clip_paths(tmp_path):
    """reel.py exclude'a KLİP YOLLARI koyar — bu klip bir daha DÖNMEMELİ."""
    calls = {"download": []}
    src = _Src(_cands("a", "b"), calls)
    d = FootageDeps(sources=[src], verify_footage=lambda *a, **kw: True)

    first = match_beat_clip("q", cache_dir=tmp_path, verify=False, deps=d)
    assert first is not None
    second = match_beat_clip("q", cache_dir=tmp_path, verify=False, deps=d,
                             exclude={str(first)})
    assert second is not None
    assert second != first, "exclude çalışmadı → aynı klip yeniden döndü"


def test_rejected_candidates_are_not_re_judged(monkeypatch, tmp_path):
    """Aynı aday, aynı videoda İKİNCİ kez vision'a SOKULMAMALI (red hafızası).

    Gerçek ``verify_clip_matches`` üzerinde test edilir — önbellek orada yaşar,
    çünkü yargının anlamını (matches/in_context/clear) bilen tek yer orasıdır.
    """
    import short_bot.footage_matcher as fm

    judged: list = []

    def fake_judge(path, query, *, vision_call, context=""):
        judged.append(query)
        return fm._FootageVerdict(content="a seagull", matches=False,
                                  in_context=False, clear=True, reason="martı")

    monkeypatch.setattr(fm, "_judge_image_file", fake_judge)

    class _R:
        status_code = 200
        content = b"jpg"

    monkeypatch.setattr("requests.get", lambda *a, **kw: _R())

    seen: dict = {}
    url = "https://x/seagull.jpg"
    assert fm.verify_clip_matches(url, "condor", vision_call=object(), seen=seen) is False
    assert len(judged) == 1
    # Aynı aday tekrar: vision'a GİTMEZ, önbellekten yanıtlanır
    assert fm.verify_clip_matches(url, "condor", vision_call=object(), seen=seen) is False
    assert len(judged) == 1, "reddedilen aday yeniden yargılandı"


def test_prompt_keeps_in_context_independent_of_matches():
    """in_context, matches'ten BAĞIMSIZ ve ondan GENİŞ sorulmalı.

    GERÇEK REGRESYON: prompt'ta "matches=true ise in_context de true olmalı"
    yazıyordu. Model bunu TERS yönde uyguladı — matches=false verince tutarlı
    kalmak için in_context'i de false yaptı. Kendi gerekçesi: "Konuya tam olarak
    uymadığı için matches false olur. Destekleyici görüntü olarak da
    kullanılamayacağı için in_context de false olur."
    Sonuç: bir üretim koşusunda 13/13 klip BAĞLAM DIŞI diye reddedildi —
    "A glacial river flows through a rocky canyon" bile (konu: buzul erimesi).
    """
    import short_bot.footage_matcher as fm
    p = fm._judge_prompt("melting ice rivers", context="buzul erimesi")
    assert "BAĞIMSIZ" in p, "bağımsızlık vurgulanmıyor"
    assert "matches=true ise in_context de true olmalı" not in p, (
        "iki alanı birbirine bağlayan cümle geri geldi — model geriye doğru "
        "akıl yürütüp in_context'i de düşürür")
    # matches=false + in_context=true örneği prompt'ta AÇIKÇA gösterilmeli
    assert "matches=false" in p and "in_context=TRUE" in p


def test_prompt_rejects_a_misleading_different_creature():
    """BAĞLAM b-roll'ü, izleyiciyi YANILTACAK farklı bir canlı OLMAMALI.

    GERÇEK HATA (kanguru videosu): gevşek kapı "aynı dünya = vahşi yaşam" diye
    fazla cömert davrandı → anlatım "yeni doğan kanguru" derken ekranda KUŞ,
    "keseye tırmanır" derken KEÇİ, "avcılar" derken VAŞAK çıktı. İzleyici kanguru
    duyup keçi görüyor.

    Doğru ayrım: destekleyici b-roll = ORTAM/HABİTAT/atmosfer. Konunun öznesi
    sanılacak BAŞKA bir tanınabilir canlı DEĞİL.
    """
    import short_bot.footage_matcher as fm
    p = fm._judge_prompt("kangaroo joey pouch", context="yeni doğan kanguru yavrusu")
    assert "YANILTICI" in p, "yanıltıcı-canlı kuralı prompt'ta yok"
    # Somut karşı-örnekler verilmeli (soyut kural tek başına yetmiyor)
    assert "KEÇİ" in p or "keçi" in p
    # Habitat/ortam b-roll'ü hâlâ KABUL edilmeli (yoksa vision'sız çöpe düşeriz)
    assert "habitat" in p.lower() or "manzara" in p.lower()


def test_in_context_candidates_are_banked_during_the_strict_scan(tmp_path):
    """Katı tarama sırasında BAĞLAMA UYAN adaylar kenara NOT EDİLİR.

    Böylece katı kapı boş çıkınca YENİDEN ARAMAYA gerek kalmaz: elde zaten
    yargılanmış, bağlamda, net adaylar vardır.

    GERÇEK MALİYET: gevşek kapıyı ayrı bir ikinci tarama olarak kurmuştum —
    canlı koşuda 121 vision çağrısına ulaşıp üretimi dakikalarca uzattı. Oysa
    in_context yargısı katı taramada ZATEN alınmıştı; ikinci arama tamamen israf.
    """
    calls = {"download": []}
    judged: list = []
    src = _Src(_cands("butterfly", "eagle"), calls)

    def verify(url, query, *, seen=None, **kw):
        # Gerçek verify_clip_matches gibi: önbellekte varsa VISION'A GİTMEZ
        k = _seen_key(query, url)
        if seen is not None and k in seen:
            v = seen[k]
        else:
            judged.append(url)          # = gerçek vision çağrısı
            v = _V(matches=False, in_context=("eagle" in url), clear=True)
            if seen is not None:
                seen[k] = v
        return v.matches and v.clear

    d = FootageDeps(sources=[src], verify_footage=verify)
    bank: list = []
    out = match_beat_clip("condor wing span", cache_dir=tmp_path, verify=True,
                          vision_call=object(), deps=d, seen={}, bank=bank)
    assert out is None, "katı kapı kartalı geçirmemeliydi"
    assert len(judged) == 2                       # iki aday BİR kez yargılandı
    assert len(bank) == 1, "bağlama uyan aday not edilmedi"
    assert "eagle" in str(bank[0][2].url)         # ("dl", source, candidate)


def test_banked_candidate_is_used_without_a_second_search(tmp_path):
    """Kenara notlanan aday, YENİDEN ARAMA ve YENİDEN VISION olmadan indirilir."""
    calls = {"download": []}
    searches: list = []
    judged: list = []

    class _CountingSrc(_Src):
        def search(self, q, *, max_results, orientation):
            searches.append(q)
            return self._cands

    src = _CountingSrc(_cands("eagle"), calls)

    def verify(url, query, *, seen=None, **kw):
        judged.append(url)
        if seen is not None:
            seen[_seen_key(query, url)] = _V(matches=False, in_context=True, clear=True)
        return False

    d = FootageDeps(sources=[src], verify_footage=verify)
    bank: list = []
    assert match_beat_clip("condor", cache_dir=tmp_path, verify=True,
                           vision_call=object(), deps=d, seen={}, bank=bank) is None
    n_search, n_judge = len(searches), len(judged)
    assert bank

    clip = download_banked(bank, cache_dir=tmp_path, exclude=set())
    assert clip is not None and clip.name == "eagle.mp4"
    assert len(searches) == n_search, "yeniden arama yapıldı"
    assert len(judged) == n_judge, "yeniden vision çağrısı yapıldı"


def test_banked_download_respects_exclude(tmp_path):
    """Notlanan aday zaten bu videoda kullanıldıysa ATLANIR."""
    calls = {"download": []}
    src = _Src(_cands("eagle", "hawk"), calls)

    def verify(url, query, *, seen=None, **kw):
        if seen is not None:
            seen[_seen_key(query, url)] = _V(matches=False, in_context=True, clear=True)
        return False

    d = FootageDeps(sources=[src], verify_footage=verify)
    bank: list = []
    match_beat_clip("condor", cache_dir=tmp_path, verify=True,
                    vision_call=object(), deps=d, seen={}, bank=bank)
    first = download_banked(bank, cache_dir=tmp_path, exclude=set())
    second = download_banked(bank, cache_dir=tmp_path, exclude={str(first)})
    assert second is not None and second != first
