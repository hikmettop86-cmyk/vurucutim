"""Reel montajı: çok-klip hızlı kesme + zoom-punch + overlay + ses miksi.

PoC'de (scratchpad/poc/make_poc2.py) doğrulanmış ffmpeg mantığı.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from short_bot.reel_framing import SUBJECT_BIAS, ken_burns, ken_burns_vf
from short_bot.reel_grade import grade_vf, luma_delta, measure_luma
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
    zoom: bool = True, clip_starts: list | None = None,
    hook_punch: bool = False,
    subject_xs: list | None = None,   # alt-kesim başına öznenin yatay konumu (0-1)
    color_grade: bool = True,         # master renk grade + klip normalizasyonu
    seed: int = 0,                    # Ken Burns hareketi (deterministik)
    punch_at: list[float] | None = None,   # vurgu anlarında zoom darbesi (bkz. reel_punch)
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
                    luma_cache[key] = measure_luma(Path(clip), ffmpeg_path)
                g = grade_vf(luma_delta(luma_cache[key]))
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
        pvf = punch_vf(punch_at or [], w=W, h=H)
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
            cmd += ["-stream_loop", "-1", "-i", str(music_path)]
            parts.append(f"[{idx}:a]volume={music_volume:g}[bgm0]")
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

        if sfx_at_cut and cut_times:
            for k, ct in enumerate(cut_times):
                if k >= len(sfx_at_cut) or sfx_at_cut[k] is None:
                    continue
                cmd += ["-i", str(sfx_at_cut[k])]
                # Seviye ayardan gelir (eskiden SABİT 0.6 → anlatımla yarışıyordu).
                # Kütüphanedeki SFX zaten kırpılmış + seviyesi eşitlenmiş vurgular.
                parts.append(f"[{idx}:a]adelay={int(ct*1000)}|{int(ct*1000)},"
                             f"volume={sfx_volume:g}[wh{k}]")
                labels.append(f"[wh{k}]")
                idx += 1
        # MASTER: YouTube ~-14 LUFS'a normalize eder; oraya yakın teslim edip -1 dBTP
        # pay bırakmak transcode'da kırpılmayı önler.
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:"
                     f"duration=first:dropout_transition=0:normalize=0[mixed]")
        # alimiter ŞART (kozmetik değil): loudnorm'un tek-geçiş dinamik modu amix
        # çıkışında NaN/Inf örnek üretebiliyor ve AAC kodlayıcı kareyi reddediyor
        # ("Input contains (near) NaN/+-Inf" → Error submitting audio frame).
        # Limiter bunu kırpar — ve zaten doğru mastering zinciri budur:
        # normalize → tepe sınırla. aresample: loudnorm çıkışı 192 kHz'e yükselir.
        parts.append(f"[mixed]loudnorm=I={MASTER_LUFS:g}:TP={MASTER_TP:g}:LRA=11,"
                     f"alimiter=limit={MASTER_LIMIT:g},aresample=48000[a]")
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
                "-t", f"{duration_s:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(out_path)]
        p = _run(cmd)
        if p.returncode != 0:
            raise RuntimeError(f"final montaj başarısız: {p.stderr[-800:]}")
    return out_path
