"""Reel montajı: çok-klip hızlı kesme + zoom-punch + overlay + ses miksi.

PoC'de (scratchpad/poc/make_poc2.py) doğrulanmış ffmpeg mantığı.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from short_bot.reel_framing import SUBJECT_BIAS, ken_burns, ken_burns_vf
from short_bot.reel_grade import grade_vf, luma_delta, measure_levels
from short_bot.reel_punch import punch_vf

W, H = 1080, 1920
_ZOOMPAN = ("zoompan=z='if(lte(on,9),1.16-0.0178*on,min(1.06,1.0+0.0006*(on-9)))'"
            ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30")

# --- SES MİKSİ ------------------------------------------------------------
# DUCKING: müzik konuşma altında otomatik çekilir, boşluklarda yükselir. Bu olmadan
# müzik ya duyulmaz (sabit -20 dB'de gömülü) ya da konuşmayı boğar. Release yeterince
# uzun olmalı, yoksa müzik heceler arasında "pompalar".
DUCK_THRESHOLD = 0.03   # ölçüldü: bu eşik/oranla müzik konuşma altında ~11 dB çekilir
DUCK_RATIO = 10         # (8 → sadece 6.7 dB; 12 → 14.4 dB, fazla sert/pompalı)
DUCK_ATTACK_MS = 5
DUCK_RELEASE_MS = 350
# MASTER: YouTube ~-14 LUFS'a normalize eder. Oraya yakın teslim et, -1 dBTP pay bırak.
MASTER_LUFS = -14
MASTER_TP = -1
MASTER_LIMIT = 0.891   # -1 dBFS tepe tavanı (aynı zamanda loudnorm'un NaN'ını kırpar)


# Ses karesi düşüşü sessizdir; bu kadar boşluk KUSUR sayılır (kodlayıcı gecikmesi
# ~0.05sn olabilir, gerçek düşüşler saniyeler mertebesindeydi).
MAX_AUDIO_GAP_S = 0.5


def measure_lufs(path: Path, ffmpeg_path: str = "ffmpeg") -> float | None:
    """Karışımın bütünleşik yüksekliği (LUFS). İki geçişli mastering için:
    ölçüp SABİT kazanç uygularız — dinamik loudnorm NaN üretip AAC'nin kare
    düşürmesine yol açıyordu."""
    import json as _json
    p = _run([ffmpeg_path, "-hide_banner", "-i", str(path), "-af",
              "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"])
    err = p.stderr or ""
    i = err.find('"input_i"')
    if i < 0:
        return None
    a, b = err.rfind("{", 0, i), err.find("}", i)
    try:
        return float(_json.loads(err[a:b + 1])["input_i"])
    except Exception:
        return None


def _duration(path: Path) -> float | None:
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float((p.stdout or "").strip())
    except Exception:
        return None


def audio_gap_s(video: Path, duration_s: float, ffmpeg_path: str = "ffmpeg") -> float:
    """Videonun sesinde KAÇ SANİYE eksik var.

    ffmpeg ses karesi düşürdüğünde çıkış kodu 0 verir: zaman damgaları ilerler ama
    örnekler yoktur. Örnek sayısı × 1024 / örnekleme_hızı ile beklenen süreyi
    kıyaslamak bunu yakalar (gerçek hata: 310 kare = 6.6sn sessizce düşmüştü).
    """
    # csv alanları ffprobe'un KENDİ sırasında gelir, istenen sırada değil —
    # anahtarla okumak şart (ilk denemede sample_rate/nb_frames yer değiştirdi ve
    # denetim bozuk videoyu "temiz" gördü).
    p = _run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
              "stream=nb_frames,sample_rate", "-of", "default=nw=1", str(video)])
    alan = {}
    for ln in (p.stdout or "").splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            alan[k.strip()] = v.strip()
    try:
        icerik = int(alan["nb_frames"]) * 1024 / int(alan["sample_rate"])
    except Exception:
        return 0.0     # okunamadıysa yargılama (fail-open)
    return max(0.0, duration_s - icerik)


def _run(cmd) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


# Açılış kalıp-kırıcı: sert zoom-punch (1.25 → 1.0, ~1.5sn). İzleyici ilk
# saniyede kalır ya da kaçar — düz açılış retention sızdırır.
_PUNCH = ("zoompan=z='if(lte(on,45),1.25-0.0055*on,1.0)'"
          ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30")


def _normalize_segment(clip: Path, span_s: float, out: Path, *, fps: int,
                       ffmpeg: str, zoom: bool, start_s: float = 0.0,
                       punch: bool = False, subject_x: float | None = None,
                       move: dict | None = None, grade: str = "") -> None:
    """Klibi 9:16 segmente çevir: ÖZNE-FARKINDA crop + Ken Burns + master grade.

    ÖZNE-FARKINDA CROP: 16:9'u 9:16'ya kırparken hep MERKEZDEN kesiyorduk —
    araştırma bunu otomatik faceless videonun "1 numaralı görsel ele veren işareti"
    diye adlandırıyor (özne kenardaysa yarısı kesilir). Özne konumunu ZATEN
    biliyoruz (locate_subject); artık kadraj ona göre kayıyor.

    GRADE: farklı kaynaklardan gelen kliplerin renk zıplaması, "bunu bir script
    birleştirdi" diye bağırır. Ortak look + klibe özel parlaklık normalizasyonu.
    """
    # Özneyi izleyen crop. Kaynak boyutu bilinmediği için crop'u ifadeyle kur:
    # scale ile kısa kenarı doldur, sonra ÖZNENİN etrafından kes.
    if subject_x is None:
        crop = f"crop={W}:{H}"
    else:
        sx = min(1.0, max(0.0, float(subject_x)))
        # (iw-ow) kadar yer var; özneyi ortala, kenara dayanmasın diye SUBJECT_BIAS.
        cx = f"(iw-{W})/2+((iw*{sx:g}-{W}/2)-(iw-{W})/2)*{SUBJECT_BIAS:g}"
        crop = f"crop={W}:{H}:x='max(0,min(iw-{W},{cx}))':y='(ih-{H})/2'"
    base = f"scale={W}:{H}:force_original_aspect_ratio=increase,{crop}"

    if punch:
        motion = _PUNCH
    elif move is not None:
        motion = ken_burns_vf(move, w=W, h=H, fps=fps,
                              frames=max(1, int(span_s * fps)), subject_x=subject_x)
    else:
        motion = _ZOOMPAN
    tail = f",{grade}" if grade else ""
    vf_zoom = f"{base},{motion}{tail},format=yuv420p"
    vf_plain = f"{base},fps={fps}{tail},format=yuv420p"
    # start_s: AYNI klibin farklı anından başla (alt-kesim çeşitliliği) — hızlı
    # kesimde bir beat'in alt-kesimleri aynı klibi tekrar kullanabilir.
    seek = ["-ss", f"{start_s:.3f}"] if start_s > 0 else []
    for vf in ([vf_zoom, vf_plain] if (zoom or punch or move) else [vf_plain]):
        p = _run([ffmpeg, "-y", "-stream_loop", "-1", *seek, "-i", str(clip),
                  "-t", f"{span_s:.3f}", "-vf", vf, "-an",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)])
        if p.returncode == 0:
            return
    raise RuntimeError(f"segment normalize başarısız ({clip.name}): {p.stderr[-500:]}")


def assemble_reel(
    *, clip_paths: list[Path], seg_spans: list[tuple[float, float]],
    frames_dir: Path, narration_path: Path, music_path: Path | None,
    out_path: Path, cut_times: list[float], duration_s: float,
    fps: int = 30, ffmpeg_path: str = "ffmpeg", music_volume: float = 0.10,
    narration_volume: float = 1.0, sfx_volume: float = 0.22,
    music_duck: bool = True,
    riser: tuple | None = None,       # (path, süre_sn) — TEPESİ reveal'e denk gelir
    impact: Path | None = None,       # reveal karesinde vuruş
    reveal_s: float | None = None,    # TEPE anı (yoksa gramer kurulmaz)
    riser_volume: float = 0.35,
    impact_volume: float = 0.40,
    sfx_at_cut: list | None = None,
    sfx_gains: list[float] | None = None,   # kesim başına seviye çarpanı (bkz. reel_interrupt)
    sting: Path | None = None,        # açılış ses imzası (t=0, bkz. reel_identity)
    sting_volume: float = 0.35,
    zoom: bool = True, clip_starts: list | None = None,
    hook_punch: bool = False,
    subject_xs: list | None = None,   # alt-kesim başına öznenin yatay konumu (0-1)
    color_grade: bool = True,         # master renk grade + klip normalizasyonu
    seed: int = 0,                    # Ken Burns hareketi (deterministik)
    punch_at: list[float] | None = None,   # vurgu anlarında zoom darbesi (bkz. reel_punch)
    music_start_s: float = 0.0,       # parçanın sessiz girişini atla (bkz. music_profile)
    music_gain_db: float = 0.0,       # kütüphane seviye farkını eşitle
) -> Path:
    """Segment klipleri + overlay + ses → mp4. clip_paths ve seg_spans aynı boyda."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for c in clip_paths:
        if not Path(c).exists():
            raise FileNotFoundError(f"Reel klibi yok: {c}")
    if not Path(narration_path).exists():
        raise FileNotFoundError(f"Anlatım sesi yok: {narration_path}")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        seg_files = []
        starts = list(clip_starts or [])
        # MASTER GRADE: klip başına parlaklık ölçümü ÖNBELLEKLENİR — aynı klip birçok
        # alt-kesimde geçiyor, her seferinde ölçmek boşuna.
        luma_cache: dict[str, float] = {}
        for i, (clip, (a, b)) in enumerate(zip(clip_paths, seg_spans)):
            span = max(0.5, b - a)
            sf = td / f"seg_{i}.mp4"
            g = ""
            if color_grade:
                key = str(clip)
                if key not in luma_cache:
                    # TEPE de ölçülür: ortalama tek başına "siyah zeminde parlayan
                    # mikroplar" ile "kötü pozlanmış klip"i ayırt edemez.
                    luma_cache[key] = measure_levels(Path(clip), ffmpeg_path)
                lum, pk = luma_cache[key]
                g = grade_vf(luma_delta(lum, pk))
            _normalize_segment(Path(clip), span, sf, fps=fps,
                               ffmpeg=ffmpeg_path, zoom=zoom,
                               start_s=(starts[i] if i < len(starts) else 0.0),
                               punch=(hook_punch and i == 0),
                               subject_x=(subject_xs[i]
                                          if subject_xs and i < len(subject_xs)
                                          else None),
                               move=(None if (hook_punch and i == 0)
                                     else ken_burns(seed=seed, index=i)),
                               grade=g)
            seg_files.append(sf)
        lst = td / "concat.txt"
        lst.write_text("".join(f"file '{f.as_posix()}'\n" for f in seg_files),
                       encoding="utf-8")
        footage = td / "footage.mp4"
        p = _run([ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                  "-c", "copy", str(footage)])
        if p.returncode != 0:
            raise RuntimeError(f"concat başarısız: {p.stderr[-500:]}")

        cmd = [ffmpeg_path, "-y", "-i", str(footage),
               "-framerate", str(fps), "-i", str(Path(frames_dir) / "f_%05d.png"),
               "-i", str(narration_path)]
        # VURGU PUNCH-IN: sayı/tepe anlarında görüntü bir tık yaklaşır — sesle
        # görüntüyü kilitleyen tek hamle. Overlay'den ÖNCE uygulanır: yazılar
        # zoom'la birlikte büyümemeli, yoksa altyazı kadrajdan taşar.
        pvf = punch_vf(punch_at or [], w=W, h=H, fps=fps)
        if pvf:
            parts = [f"[0:v]{pvf}[pv]", "[pv][1:v]overlay=0:0[v]"]
        else:
            parts = ["[0:v][1:v]overlay=0:0[v]"]
        # Ducking için anlatım İKİ yere gider: mikse ve kompresörün yan-zincirine.
        duck = music_path is not None and music_duck
        if duck:
            parts.append(f"[2:a]volume={narration_volume:g},asplit=2[nar][narsc]")
        else:
            parts.append(f"[2:a]volume={narration_volume:g}[nar]")
        labels = ["[nar]"]
        idx = 3
        if music_path is not None:
            # GİRİŞİ ATLA + SEVİYEYİ EŞİTLE. Parçaları 0:00'dan başlatıyorduk; stok
            # müziklerin çoğu yavaş kuruluyor (ölçüldü: bir parça tam gücüne 60
            # SANİYEDE ulaşıyor) → 30sn'lik shorts yalnız sessiz girişi kullanıyor
            # ve müzik DUYULMUYORDU. Kütüphanedeki 24.9 dB'lik seviye yayılımı da
            # aynı ayarla bir videoyu sessiz, ötekini bağıran yapıyordu.
            seek = ["-ss", f"{music_start_s:.2f}"] if music_start_s > 0 else []
            cmd += ["-stream_loop", "-1", *seek, "-i", str(music_path)]
            gain = f"volume={music_gain_db:g}dB," if music_gain_db else ""
            parts.append(f"[{idx}:a]{gain}volume={music_volume:g}[bgm0]")
            if duck:
                # DUCKING: müzik konuşma altında otomatik çekilir, BOŞLUKLARDA
                # yükselir. Bu olmadan müziği duyulur seviyeye çıkarmak konuşmayı
                # boğar → izleyici kelime ayıklamak için çaba harcar → kaydırma.
                # Kısa formatta enerjiyi taşıyan mekanizma budur.
                # apad ŞART: sidechaincompress çıkışı girişten ~0.3sn KISA (iç
                # gecikme). Padsiz kalırsa videonun SONUNDA müzik kesiliyor — ve
                # sonda susan müzik LOOP'U BOZAR: izleyici videonun bittiğini
                # duyar, başa dönmez. amix duration=first olduğu için pad zararsız.
                parts.append(f"[bgm0][narsc]sidechaincompress="
                             f"threshold={DUCK_THRESHOLD:g}:ratio={DUCK_RATIO:g}:"
                             f"attack={DUCK_ATTACK_MS:g}:release={DUCK_RELEASE_MS:g},"
                             f"apad[bgm]")
            else:
                parts.append("[bgm0]anull[bgm]")
            labels.append("[bgm]")
            idx += 1
        # RISER → IMPACT: riser bir TAHMİN MAKİNESİDİR — beyne "bir şey geliyor" der
        # ve kaydırma dürtüsünü bastırır (çözülmeden gidemezsin); impact tahmini
        # ÖDÜLLENDİRİR. Riser'ın TEPESİ sondadır → BİTİŞİNİ reveal karesine hizala.
        if reveal_s is not None and reveal_s > 0:
            if riser is not None:
                r_path, r_dur = riser
                r_at = max(0.0, reveal_s - float(r_dur))
                cmd += ["-i", str(r_path)]
                parts.append(f"[{idx}:a]adelay={int(r_at*1000)}|{int(r_at*1000)},"
                             f"volume={riser_volume:g}[riser]")
                labels.append("[riser]")
                idx += 1
            if impact is not None:
                i_at = reveal_s
                cmd += ["-i", str(impact)]
                parts.append(f"[{idx}:a]adelay={int(i_at*1000)}|{int(i_at*1000)},"
                             f"volume={impact_volume:g}[impact]")
                labels.append("[impact]")
                idx += 1

        # STING — kanalın AÇILIŞ SES İMZASI, t=0'da. Bir "ses logosu": izleyici onu
        # bilinçli fark etmez ama üçüncü videoda TANIR, ve tanıdık şeye abone olunur.
        # Faceless kanalda tanınmayı taşıyan kanallardan biri budur (bkz. reel_identity).
        if sting is not None and Path(sting).exists():
            cmd += ["-i", str(sting)]
            parts.append(f"[{idx}:a]volume={sting_volume:g}[sting]")
            labels.append("[sting]")
            idx += 1

        if sfx_at_cut and cut_times:
            for k, ct in enumerate(cut_times):
                if k >= len(sfx_at_cut) or sfx_at_cut[k] is None:
                    continue
                cmd += ["-i", str(sfx_at_cut[k])]
                # Seviye ayardan gelir (eskiden SABİT 0.6 → anlatımla yarışıyordu).
                # Kütüphanedeki SFX zaten kırpılmış + seviyesi eşitlenmiş vurgular.
                # KESİM BAŞINA ÇARPAN: kesinti anları yüksek, ötekiler kısık. Hepsi
                # aynı seviyedeyken hiçbiri vurgu değildi — kontrast olmadan vurgu olmaz.
                g = sfx_gains[k] if (sfx_gains and k < len(sfx_gains)) else 1.0
                parts.append(f"[{idx}:a]adelay={int(ct*1000)}|{int(ct*1000)},"
                             f"volume={sfx_volume * g:g}[wh{k}]")
                labels.append(f"[wh{k}]")
                idx += 1
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:"
                     f"duration=first:dropout_transition=0:normalize=0[mixed]")
        # MASTER — İKİ GEÇİŞ, TEK GEÇİŞ DEĞİL.
        # loudnorm'un tek-geçiş DİNAMİK modu NaN/Inf örnek üretebiliyor; AAC kodlayıcı
        # o kareleri REDDEDİYOR ve ffmpeg onları SESSİZCE DÜŞÜRÜP çıkış kodu 0
        # veriyor. Sonuç: zaman damgaları 32sn'ye gidiyor ama seste yalnız 25sn'lik
        # örnek var — ses ortadan atlıyor ve sonda kesiliyor. Ölçüldü: üretilen iki
        # videoda 310 ses karesi (6.6sn) düşmüş. alimiter bunu KURTARMIYOR: limiter
        # NaN'ı kırpmaz, NaN'ı geçirir.
        #
        # Çözüm kaynağı kurutmak: karışımı ÖNCE ölç, SONRA sabit kazanç uygula.
        # Sabit kazanç NaN üretemez. (Yan fayda: dinamik loudnorm dinamiği de
        # eziyordu — sabit kazanç anlatımın nefesini korur.)
        # Ses geçişi TÜM girdileri korur (indeksler [2:a], [3:a]... kaymasın) ama
        # yalnız ses grafiğini kullanır — video filtreleri bağlanmadan bırakılamaz.
        n_vparts = 2 if pvf else 1
        mix_wav = td / "mix.wav"
        p = _run(list(cmd) + ["-filter_complex", ";".join(parts[n_vparts:]),
                              "-map", "[mixed]", "-t", f"{duration_s:.3f}",
                              "-vn", "-c:a", "pcm_s16le", str(mix_wav)])
        if p.returncode != 0:
            raise RuntimeError(f"ses miksi başarısız: {p.stderr[-500:]}")
        gain = MASTER_LUFS - (measure_lufs(mix_wav, ffmpeg_path) or MASTER_LUFS)

        cmd2 = [ffmpeg_path, "-y", "-i", str(footage),
                "-framerate", str(fps), "-i", str(Path(frames_dir) / "f_%05d.png"),
                "-i", str(mix_wav)]
        vparts = [f"[0:v]{pvf}[pv]", "[pv][1:v]overlay=0:0[v]"] if pvf \
            else ["[0:v][1:v]overlay=0:0[v]"]
        # SABİT kazanç + tepe sınırlayıcı: doğru mastering zinciri (normalize →
        # tepe sınırla) ve NaN üretemez.
        vparts.append(f"[2:a]volume={gain:.2f}dB,"
                      f"alimiter=limit={MASTER_LIMIT:g},aresample=48000[a]")
        cmd2 += ["-filter_complex", ";".join(vparts), "-map", "[v]", "-map", "[a]",
                 "-t", f"{duration_s:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                 "-movflags", "+faststart", str(out_path)]
        p = _run(cmd2)
        if p.returncode != 0:
            raise RuntimeError(f"final montaj başarısız: {p.stderr[-800:]}")

        # SES BÜTÜNLÜK DENETİMİ. ffmpeg ses karesi düşürdüğünde ÇIKIŞ KODU 0 verir —
        # bozulma sessizdir. Ölçüt MİKSİN kendi uzunluğu: "ses videodan kısa" ayrı
        # bir durumdur (anlatım bitmiştir), biz KODLAYICININ düşürdüğü kareleri
        # arıyoruz. Mikste 32sn örnek varken çıkışta 25sn olması KUSURDUR.
        beklenen = min(duration_s, _duration(mix_wav) or duration_s)
        eksik = audio_gap_s(out_path, beklenen, ffmpeg_path)
        if eksik > MAX_AUDIO_GAP_S:
            raise RuntimeError(
                f"montaj sesin {eksik:.1f} saniyesini düşürdü (süre {duration_s:.1f}sn "
                f"ama örnekler daha kısa) — video sessizce bozuk çıkardı")
    return out_path
