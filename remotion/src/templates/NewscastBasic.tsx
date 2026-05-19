/**
 * NewscastBasic — Remotion port of the HTML newscast template.
 *
 * Visual identity matches the existing Jinja2 template close enough that a
 * channel can opt into the Remotion renderer without users perceiving a
 * regression. Adds two things HTML can't easily do:
 *   - Per-frame interpolation animations (header fade-in, body line reveal)
 *   - Progress bar driven by the actual frame counter, not CSS animation
 *
 * Props are validated by Zod (newscastSchema) so the Python wrapper writing
 * --props=script.json gets clear errors on schema mismatch.
 */
import React from 'react';
import {z} from 'zod';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

export const newscastSchema = z.object({
  headerTop: z.string().min(1).max(60),
  headerBottom: z.string().min(1).max(80),
  photoOverlay: z.string().max(140).default(''),
  bodyParagraph: z.string().min(1).max(800),
  category: z.string().max(40).default(''),
  handle: z.string().max(40).default(''),
  durationSeconds: z.number().positive().default(6),
  bgImageUrl: z.string().default(''),
  uiBreaking: z.string().max(40).default('SON DAKİKA'),
  // Colors mirror channel DNA. Defaults match son-dakika.
  colors: z
    .object({
      primary: z.string(),
      accent: z.string(),
      bgGrad1: z.string(),
      bgGrad2: z.string(),
      textMain: z.string(),
      textMuted: z.string(),
    })
    .default({
      primary: '#c8102e',
      accent: '#ffb81c',
      bgGrad1: '#0a1733',
      bgGrad2: '#1a2a4f',
      textMain: '#ffffff',
      textMuted: '#cccccc',
    }),
});

export type NewscastProps = z.infer<typeof newscastSchema>;

export const NEWSCAST_DEFAULTS: NewscastProps = {
  headerTop: 'SON DAKİKA',
  headerBottom: 'TEST HABERİ',
  photoOverlay: 'Önizleme için sahte içerik',
  bodyParagraph:
    'Bu Remotion entegrasyonunun proof-of-concept render ı. ' +
    'Production render i Python tarafından gönderilen JSON props ile yapılır.',
  category: 'TEST',
  handle: '@vurucutim',
  durationSeconds: 6,
  bgImageUrl: '',
  uiBreaking: 'SON DAKİKA',
  colors: {
    primary: '#c8102e',
    accent: '#ffb81c',
    bgGrad1: '#0a1733',
    bgGrad2: '#1a2a4f',
    textMain: '#ffffff',
    textMuted: '#cccccc',
  },
};

export const NewscastBasic: React.FC<NewscastProps> = ({
  headerTop,
  headerBottom,
  photoOverlay,
  bodyParagraph,
  category,
  handle,
  bgImageUrl,
  uiBreaking,
  colors,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  // Header pulses in via spring (snappy entrance, ~0.4s)
  const headerOpacity = spring({
    frame,
    fps,
    config: {damping: 200, stiffness: 220},
    durationInFrames: Math.round(fps * 0.4),
  });
  const headerTranslateY = interpolate(headerOpacity, [0, 1], [-30, 0]);

  // Body slides up from below with a longer delay so the header reads first
  const bodyDelay = Math.round(fps * 0.3);
  const bodyOpacity = spring({
    frame: frame - bodyDelay,
    fps,
    config: {damping: 200, stiffness: 180},
    durationInFrames: Math.round(fps * 0.6),
  });
  const bodyTranslateY = interpolate(bodyOpacity, [0, 1], [40, 0]);

  // Progress bar: 0% at start, 100% at end
  const progress = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateRight: 'clamp',
  });

  // Header font sizing — auto-scale on text length to avoid horizontal
  // clipping on long Turkish headlines. Top line is heavier (font-weight 900,
  // larger) than bottom, so they have separate curves. Empirically: 1080px
  // wide minus 120px side padding = 960px content; ~50px/char at 100px font.
  const topLen = headerTop.length;
  const topFontSize = topLen <= 14 ? 100
                    : topLen <= 18 ? 84
                    : topLen <= 22 ? 72
                    : 60;
  const bottomLen = headerBottom.length;
  const bottomFontSize = bottomLen <= 18 ? 70
                       : bottomLen <= 24 ? 60
                       : bottomLen <= 30 ? 52
                       : 44;

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, ${colors.bgGrad1}, ${colors.bgGrad2})`,
        fontFamily:
          "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        color: colors.textMain,
      }}
    >
      {/* Stage badge top-right */}
      <div
        style={{
          position: 'absolute',
          top: 14,
          right: 14,
          background: '#000',
          color: colors.accent,
          fontSize: 20,
          fontWeight: 800,
          letterSpacing: 1,
          padding: '8px 14px',
          borderRadius: 4,
          zIndex: 30,
        }}
      >
        {uiBreaking}
      </div>

      {/* Header */}
      <div
        style={{
          background: `linear-gradient(90deg, ${colors.primary}, ${shiftLighter(
            colors.primary,
          )})`,
          padding: '78px 60px 44px',
          textAlign: 'center',
          fontWeight: 900,
          lineHeight: 1.02,
          letterSpacing: 0.5,
          boxShadow: '0 10px 0 rgba(0,0,0,.4)',
          opacity: headerOpacity,
          transform: `translateY(${headerTranslateY}px)`,
        }}
      >
        <span style={{display: 'block', whiteSpace: 'nowrap', fontSize: topFontSize}}>
          {headerTop}
        </span>
        <span
          style={{
            display: 'block',
            whiteSpace: 'nowrap',
            marginTop: 8,
            fontSize: bottomFontSize,
          }}
        >
          {headerBottom}
        </span>
      </div>

      {/* Photo band */}
      <div
        style={{
          position: 'relative',
          height: 640,
          background: `linear-gradient(135deg, ${colors.bgGrad1}, ${colors.bgGrad2})`,
          overflow: 'hidden',
        }}
      >
        {bgImageUrl && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              backgroundImage: `url(${bgImageUrl})`,
              backgroundSize: 'cover',
              backgroundPosition: 'center',
            }}
          />
        )}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background:
              'radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,.55) 100%)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: 30,
            left: 30,
            background: 'rgba(0,0,0,.78)',
            color: '#fff',
            fontSize: 30,
            padding: '10px 18px',
            borderRadius: 8,
            fontWeight: 700,
          }}
        >
          {category}
        </div>
        {photoOverlay && (
          <div
            style={{
              position: 'absolute',
              bottom: 30,
              left: 30,
              right: 30,
              background: colors.accent,
              color: '#000',
              fontSize: 44,
              fontWeight: 900,
              padding: '14px 22px',
              textAlign: 'center',
            }}
          >
            {photoOverlay}
          </div>
        )}
      </div>

      {/* Body */}
      <div
        style={{
          flex: 1,
          padding: '50px 60px 200px',
          fontSize: 48,
          lineHeight: 1.42,
          fontWeight: 600,
          opacity: bodyOpacity,
          transform: `translateY(${bodyTranslateY}px)`,
        }}
      >
        {bodyParagraph}
      </div>

      {/* Progress bar */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 80,
          height: 6,
          background: 'rgba(255,255,255,.18)',
        }}
      >
        <div
          style={{
            width: `${progress}%`,
            height: '100%',
            background: `linear-gradient(90deg, ${colors.accent}, ${colors.primary})`,
          }}
        />
      </div>

      {/* Handle */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 30,
          textAlign: 'center',
          fontSize: 28,
          fontWeight: 700,
          color: colors.accent,
          letterSpacing: 1,
        }}
      >
        {handle}
      </div>
    </AbsoluteFill>
  );
};

/** Lighten a hex color by ~15% so the header gradient has a subtle tonal
 *  shift. Mirrors the `_primary_light` helper in renderer.py. */
function shiftLighter(hex: string): string {
  const h = hex.replace('#', '');
  if (h.length !== 6) return hex;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  const shift = (v: number, by: number) => Math.min(255, v + by);
  return `#${[shift(r, 40), shift(g, 30), shift(b, 30)]
    .map((v) => v.toString(16).padStart(2, '0'))
    .join('')}`;
}
