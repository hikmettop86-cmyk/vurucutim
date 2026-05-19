/**
 * StatHero — Remotion port of the HTML stat-hero template.
 *
 * For number-driven news (economy, polls, statistics). The body is split:
 * a JS extractor lifts the first prominent figure into a giant hero number,
 * the remaining text becomes a small caption beneath.
 *
 * Remotion advantage over the HTML version: the hero number COUNTS UP from
 * 0 to its target value over the first second of the video. Numbers feel
 * alive instead of being static text on the screen.
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

export const statHeroSchema = z.object({
  headerTop: z.string().min(1).max(60),
  headerBottom: z.string().min(1).max(80),
  photoOverlay: z.string().max(140).default(''),
  bodyParagraph: z.string().min(1).max(800),
  category: z.string().max(40).default(''),
  handle: z.string().max(40).default(''),
  durationSeconds: z.number().positive().default(6),
  bgImageUrl: z.string().default(''),
  uiBreaking: z.string().max(40).default('SON DAKİKA'),
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
      primary: '#06b6d4',
      accent: '#facc15',
      bgGrad1: '#0f172a',
      bgGrad2: '#020617',
      textMain: '#ffffff',
      textMuted: '#94a3b8',
    }),
});

export type StatHeroProps = z.infer<typeof statHeroSchema>;

export const STAT_HERO_DEFAULTS: StatHeroProps = {
  headerTop: 'ENFLASYON',
  headerBottom: 'MAYIS 2026',
  photoOverlay: 'Vergi gelirleri rekor seviyede',
  bodyParagraph:
    '%54,3 oran açıklandı; bütçe gelirleri rekor seviyede, vergi ' +
    'tahsilatı yıllık bazda artış gösterdi.',
  category: 'EKONOMİ',
  handle: '@ekonomi',
  durationSeconds: 6,
  bgImageUrl: '',
  uiBreaking: 'SON DAKİKA',
  colors: {
    primary: '#06b6d4',
    accent: '#facc15',
    bgGrad1: '#0f172a',
    bgGrad2: '#020617',
    textMain: '#ffffff',
    textMuted: '#94a3b8',
  },
};

/** Extract the first prominent number (and its remaining caption) from the
 *  body paragraph. Mirrors the JS regex in templates/stat-hero.html.j2 so
 *  visual parity holds: %25 / %54,3 / yüzde N / ₺250 milyon / 1500 / 25 bin.
 */
function extractStat(text: string): {number: string; caption: string} {
  // 1. "yüzde 25" / "yüzde 54,3"
  let m = text.match(/y[üu]zde\s+(\d{1,3}(?:[,.]\d+)?)/i);
  if (m) {
    const matchStr = m[0];
    return {
      number: '%' + m[1].replace('.', ','),
      caption: stripMatched(text, matchStr),
    };
  }
  // 2. "%54" / "%54,3"
  m = text.match(/%\s*(\d{1,3}(?:[,.]\d+)?)/);
  if (m) {
    return {
      number: '%' + m[1].replace('.', ','),
      caption: stripMatched(text, m[0]),
    };
  }
  // 3. Currency
  m = text.match(/([₺$€£]\s*\d+(?:[,.]\d+)?(?:\s*(?:milyon|milyar|bin))?)/i);
  if (m) {
    return {number: m[1].replace(/\s+/g, ' ').trim(), caption: stripMatched(text, m[0])};
  }
  // 4. Plain number ≥3 digits
  m = text.match(/(\b\d{1,3}(?:[.,]\d{3})+\b|\b\d{3,}\b)(?:\s*(milyon|milyar|bin))?/i);
  if (m) {
    return {
      number: m[1] + (m[2] ? ' ' + m[2] : ''),
      caption: stripMatched(text, m[0]),
    };
  }
  return {number: '◆', caption: text};
}

function stripMatched(text: string, match: string): string {
  return text
    .replace(match, '')
    .replace(/\s+/g, ' ')
    .replace(/^[\s,.;:]+/, '')
    .trim();
}

/** Parse a stat string to a number for the count-up animation. Returns
 *  null if not numerically interpolatable (e.g. "₺250 milyon" — keep
 *  static). */
function parseTargetNumber(stat: string): number | null {
  // %54,3 → 54.3; %25 → 25
  const pct = stat.match(/^%([\d,.]+)$/);
  if (pct) return parseFloat(pct[1].replace(',', '.'));
  // Pure digit (1500, 2500)
  const plain = stat.match(/^([\d,.]+)$/);
  if (plain) return parseFloat(plain[1].replace(/\./g, '').replace(',', '.'));
  return null;
}

function formatCountUp(target: number, isPercent: boolean, hasDecimal: boolean): string {
  const v = hasDecimal ? target.toFixed(1).replace('.', ',') : Math.round(target).toString();
  return isPercent ? `%${v}` : v;
}

export const StatHero: React.FC<StatHeroProps> = ({
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

  const {number: heroNumber, caption} = React.useMemo(
    () => extractStat(bodyParagraph),
    [bodyParagraph],
  );

  // Count-up animation: 0→target over first ~1 second
  const target = parseTargetNumber(heroNumber);
  const countDuration = Math.round(fps * 1.2);
  const countProgress = interpolate(frame, [0, countDuration], [0, 1], {
    extrapolateRight: 'clamp',
  });

  let displayNumber = heroNumber;
  if (target !== null) {
    const isPercent = heroNumber.startsWith('%');
    const hasDecimal = heroNumber.includes(',');
    // Ease-out cubic for a natural count-up
    const eased = 1 - Math.pow(1 - countProgress, 3);
    const current = target * eased;
    displayNumber = formatCountUp(current, isPercent, hasDecimal);
  }

  // Header entrance
  const headerEntrance = spring({
    frame,
    fps,
    config: {damping: 200, stiffness: 220},
    durationInFrames: Math.round(fps * 0.4),
  });
  const headerTranslateY = interpolate(headerEntrance, [0, 1], [-30, 0]);

  // Caption fades in AFTER the count-up settles
  const captionDelay = countDuration + Math.round(fps * 0.2);
  const captionEntrance = spring({
    frame: frame - captionDelay,
    fps,
    config: {damping: 200, stiffness: 180},
    durationInFrames: Math.round(fps * 0.5),
  });

  // Progress bar
  const progress = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, ${colors.bgGrad1}, ${colors.bgGrad2})`,
        fontFamily:
          "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        color: colors.textMain,
      }}
    >
      {/* Stage badge */}
      <div
        style={{
          position: 'absolute',
          top: 14,
          right: 14,
          background: colors.primary,
          color: '#fff',
          fontSize: 20,
          fontWeight: 800,
          letterSpacing: 1,
          padding: '8px 16px',
          borderRadius: 6,
          zIndex: 30,
        }}
      >
        {uiBreaking}
      </div>

      {/* Header */}
      <div
        style={{
          background: `linear-gradient(135deg, ${colors.primary}, rgba(6,182,212,0.4))`,
          padding: '70px 60px 36px',
          textAlign: 'center',
          fontWeight: 900,
          fontSize: 80,
          lineHeight: 1.05,
          letterSpacing: 0.3,
          borderBottom: `4px solid ${colors.accent}`,
          opacity: headerEntrance,
          transform: `translateY(${headerTranslateY}px)`,
        }}
      >
        <span
          style={{
            display: 'block',
            whiteSpace: 'nowrap',
            color: colors.accent,
            textShadow: '0 2px 8px rgba(0,0,0,.5)',
          }}
        >
          {headerTop}
        </span>
        <span
          style={{
            display: 'block',
            whiteSpace: 'nowrap',
            marginTop: 6,
            fontSize: 56,
            color: '#fff',
            opacity: 0.92,
          }}
        >
          {headerBottom}
        </span>
      </div>

      {/* Photo band — shorter than newscast to give the stat more room */}
      <div
        style={{
          position: 'relative',
          height: 420,
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
              filter: 'blur(0.5px) brightness(0.6)',
            }}
          />
        )}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background:
              'radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,.7) 100%)',
          }}
        />
        {category && (
          <div
            style={{
              position: 'absolute',
              top: 24,
              left: 24,
              background: 'rgba(0,0,0,.8)',
              color: colors.accent,
              fontSize: 28,
              padding: '8px 16px',
              borderRadius: 6,
              fontWeight: 700,
              letterSpacing: 1,
            }}
          >
            {category}
          </div>
        )}
        {photoOverlay && (
          <div
            style={{
              position: 'absolute',
              bottom: 24,
              left: 24,
              right: 24,
              background: colors.accent,
              color: '#0f172a',
              fontSize: 38,
              fontWeight: 900,
              padding: '14px 22px',
              textAlign: 'center',
              letterSpacing: 0.5,
            }}
          >
            {photoOverlay}
          </div>
        )}
      </div>

      {/* Body — split into hero number + caption */}
      <div
        style={{
          flex: 1,
          marginBottom: 200,
          padding: '40px 60px 30px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 800,
            fontSize: heroNumber === '◆' ? 60 : 280,
            lineHeight: 0.95,
            color: heroNumber === '◆' ? colors.textMuted : colors.accent,
            opacity: heroNumber === '◆' ? 0.5 : 1,
            letterSpacing: -4,
            textShadow:
              heroNumber === '◆'
                ? 'none'
                : '0 4px 24px rgba(250,204,21,0.35)',
            marginBottom: 12,
            whiteSpace: 'nowrap',
          }}
        >
          {displayNumber}
        </div>
        <div
          style={{
            fontSize: 38,
            lineHeight: 1.35,
            fontWeight: 500,
            color: '#fff',
            maxWidth: '100%',
            opacity: captionEntrance,
            transform: `translateY(${interpolate(captionEntrance, [0, 1], [20, 0])}px)`,
          }}
        >
          {caption}
        </div>
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
