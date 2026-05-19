/**
 * BigQuote — Remotion-only template (no HTML counterpart).
 *
 * Use case: a single quote from a public figure with attribution.
 * Common Turkish-news patterns:
 *   - "ŞAMPİYONLUK HAKKIMIZDIR." — Galatasaray Başkanı
 *   - "VERGİ ARTIŞI GÜNDEMDE YOK." — Maliye Bakanı
 *
 * Animation: dramatic letter-by-letter quote reveal (mimics oratorical
 * pacing), attribution drops in from below after the quote settles.
 * Demonstrates how to add a template without going through the HTML
 * renderer first — just write the .tsx + register in Root.tsx.
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

export const bigQuoteSchema = z.object({
  // headerTop maps to the attribution (e.g. "Maliye Bakanı")
  headerTop: z.string().min(1).max(60),
  // headerBottom is the date / source line (e.g. "Mayıs 2026")
  headerBottom: z.string().min(1).max(80),
  // photoOverlay holds the quote itself — that's where the focal weight is
  photoOverlay: z.string().min(1).max(220),
  // bodyParagraph: context / caption shown small under the attribution
  bodyParagraph: z.string().min(1).max(800),
  category: z.string().max(40).default(''),
  handle: z.string().max(40).default(''),
  durationSeconds: z.number().positive().default(6),
  bgImageUrl: z.string().default(''),
  uiBreaking: z.string().max(40).default('AÇIKLAMA'),
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
      primary: '#1e3a5f',
      accent: '#ffd700',
      bgGrad1: '#1a1a2e',
      bgGrad2: '#0f0f1e',
      textMain: '#ffffff',
      textMuted: '#a0a0b0',
    }),
});

export type BigQuoteProps = z.infer<typeof bigQuoteSchema>;

export const BIG_QUOTE_DEFAULTS: BigQuoteProps = {
  headerTop: 'Maliye Bakanı',
  headerBottom: 'Mayıs 2026',
  photoOverlay:
    'Vergi gelirleri rekor seviyede. Bütçe denk olarak ' +
    'kapanacak ve enflasyon hedeflenen aralığa düşecek.',
  bodyParagraph: 'Açıklama bugün düzenlenen basın toplantısında yapıldı.',
  category: 'EKONOMİ',
  handle: '@ekonomi',
  durationSeconds: 6,
  bgImageUrl: '',
  uiBreaking: 'AÇIKLAMA',
  colors: {
    primary: '#1e3a5f',
    accent: '#ffd700',
    bgGrad1: '#1a1a2e',
    bgGrad2: '#0f0f1e',
    textMain: '#ffffff',
    textMuted: '#a0a0b0',
  },
};

/** Heuristic: longer quotes get a smaller font so the entire quote fits.
 *  Anchors tuned against 1080×1920 viewport with 80px side padding. */
function quoteFontSize(len: number): number {
  if (len <= 60) return 88;
  if (len <= 100) return 72;
  if (len <= 150) return 60;
  return 52;
}

export const BigQuote: React.FC<BigQuoteProps> = ({
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

  // Quote reveal: fade-in over ~0.6s with a slight upward translate.
  // Real letter-by-letter would be expensive (Remotion would re-mount the
  // whole text node per frame); a simple opacity+translate spring is the
  // accepted compromise.
  const quoteEntrance = spring({
    frame,
    fps,
    config: {damping: 200, stiffness: 110},
    durationInFrames: Math.round(fps * 0.6),
  });
  const quoteOpacity = quoteEntrance;
  const quoteTranslate = interpolate(quoteEntrance, [0, 1], [40, 0]);

  // Attribution drops in AFTER the quote settles (~0.8s delay).
  const attributionDelay = Math.round(fps * 0.8);
  const attributionEntrance = spring({
    frame: frame - attributionDelay,
    fps,
    config: {damping: 200, stiffness: 180},
    durationInFrames: Math.round(fps * 0.5),
  });

  // Caption fades in last
  const captionDelay = attributionDelay + Math.round(fps * 0.5);
  const captionEntrance = spring({
    frame: frame - captionDelay,
    fps,
    config: {damping: 200, stiffness: 180},
    durationInFrames: Math.round(fps * 0.4),
  });

  // Progress bar (matches stadium / stat-hero pattern)
  const progress = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateRight: 'clamp',
  });

  const qSize = quoteFontSize(photoOverlay.length);

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(155deg, ${colors.bgGrad1}, ${colors.bgGrad2})`,
        fontFamily:
          "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        color: colors.textMain,
      }}
    >
      {/* Optional faint background image (heavily dimmed so quote stays legible) */}
      {bgImageUrl && (
        <AbsoluteFill
          style={{
            backgroundImage: `url(${bgImageUrl})`,
            backgroundSize: 'cover',
            backgroundPosition: 'center',
            opacity: 0.15,
            filter: 'blur(2px)',
          }}
        />
      )}

      {/* Stage badge */}
      <div
        style={{
          position: 'absolute',
          top: 36,
          right: 36,
          background: colors.accent,
          color: '#0f0f1e',
          fontSize: 22,
          fontWeight: 800,
          letterSpacing: 1.5,
          padding: '10px 18px',
          borderRadius: 4,
          zIndex: 30,
        }}
      >
        {uiBreaking}
      </div>

      {category && (
        <div
          style={{
            position: 'absolute',
            top: 44,
            left: 36,
            fontSize: 18,
            fontWeight: 700,
            color: colors.accent,
            letterSpacing: 2,
            opacity: 0.9,
          }}
        >
          {category}
        </div>
      )}

      {/* Big quote — vertically centered, large quotation marks for drama */}
      <div
        style={{
          position: 'absolute',
          inset: '32% 80px 32% 80px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          opacity: quoteOpacity,
          transform: `translateY(${quoteTranslate}px)`,
        }}
      >
        <div
          style={{
            fontSize: 220,
            fontWeight: 900,
            color: colors.accent,
            lineHeight: 0.7,
            marginBottom: -20,
            opacity: 0.55,
          }}
        >
          “
        </div>
        <div
          style={{
            fontSize: qSize,
            lineHeight: 1.2,
            fontWeight: 700,
            color: '#fff',
            paddingLeft: 16,
            textShadow: '0 4px 18px rgba(0,0,0,.45)',
          }}
        >
          {photoOverlay}
        </div>
        <div
          style={{
            fontSize: 220,
            fontWeight: 900,
            color: colors.accent,
            lineHeight: 0.7,
            marginTop: 4,
            opacity: 0.55,
            textAlign: 'right',
          }}
        >
          ”
        </div>
      </div>

      {/* Attribution bar */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 240,
          textAlign: 'center',
          opacity: attributionEntrance,
          transform: `translateY(${interpolate(attributionEntrance, [0, 1], [30, 0])}px)`,
        }}
      >
        <div
          style={{
            fontSize: 40,
            fontWeight: 800,
            color: colors.accent,
            letterSpacing: 1,
          }}
        >
          — {headerTop}
        </div>
        <div
          style={{
            marginTop: 6,
            fontSize: 26,
            color: colors.textMuted,
          }}
        >
          {headerBottom}
        </div>
      </div>

      {/* Caption */}
      <div
        style={{
          position: 'absolute',
          left: 80,
          right: 80,
          bottom: 150,
          textAlign: 'center',
          fontSize: 24,
          lineHeight: 1.4,
          color: colors.textMuted,
          opacity: captionEntrance,
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
          bottom: 84,
          height: 6,
          background: 'rgba(255,255,255,.12)',
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
          bottom: 32,
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
