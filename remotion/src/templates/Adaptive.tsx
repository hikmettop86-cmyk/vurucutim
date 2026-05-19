/**
 * Adaptive — dimension-driven composable template.
 *
 * Replaces the "one .tsx per look" pattern with one template that takes a
 * `dimensions` record selecting from a small set of discrete options per
 * axis. 3 dimensions × 3 options each = 27 visually distinct looks from
 * one file. Channel DNA palette/fonts are still applied on top, so each
 * combination further multiplies by the DNA space.
 *
 * Dimensions:
 *   - headerStyle:    banner-flat | banner-skewed | hero-overlay
 *   - photoTreatment: full-bleed  | banded        | blur-bg
 *   - bodyStyle:      paragraph   | quote         | stat-hero
 *
 * When `dimensions` is null/missing, defaults to a newscast-ish recipe.
 * Sub-component sections live in this file to keep the dimension wiring
 * obvious; once 4+ options on any axis appear, split into separate files.
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

const headerStyles = ['banner-flat', 'banner-skewed', 'hero-overlay'] as const;
const photoTreatments = ['full-bleed', 'banded', 'blur-bg'] as const;
const bodyStyles = ['paragraph', 'quote', 'stat-hero'] as const;

export const adaptiveSchema = z.object({
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
      primary: '#c8102e',
      accent: '#ffb81c',
      bgGrad1: '#0a1733',
      bgGrad2: '#1a2a4f',
      textMain: '#ffffff',
      textMuted: '#cccccc',
    }),
  dimensions: z
    .object({
      headerStyle: z.enum(headerStyles).default('banner-flat'),
      photoTreatment: z.enum(photoTreatments).default('full-bleed'),
      bodyStyle: z.enum(bodyStyles).default('paragraph'),
    })
    .default({
      headerStyle: 'banner-flat',
      photoTreatment: 'full-bleed',
      bodyStyle: 'paragraph',
    }),
});

export type AdaptiveProps = z.infer<typeof adaptiveSchema>;
export type AdaptiveDimensions = AdaptiveProps['dimensions'];

export const ADAPTIVE_DEFAULTS: AdaptiveProps = {
  headerTop: 'SON DAKİKA',
  headerBottom: 'ADAPTIVE TEMPLATE',
  photoOverlay: 'Tek dosyadan 27 kombinasyon',
  bodyParagraph:
    'Adaptive template, üç boyutta üçer seçenek kombinasyonu ile içeriğe ' +
    'uyum sağlayan görsel varyasyonlar üretir. DNA renkleri her birinin ' +
    'üstüne uygulanır.',
  category: 'SİSTEM',
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
  dimensions: {
    headerStyle: 'banner-flat',
    photoTreatment: 'full-bleed',
    bodyStyle: 'paragraph',
  },
};

type Colors = AdaptiveProps['colors'];

// ─── Header sub-renderers ──────────────────────────────────────────────────

function headerFontSizes(topLen: number, bottomLen: number) {
  return {
    top: topLen <= 14 ? 96 : topLen <= 18 ? 80 : topLen <= 22 ? 68 : 56,
    bottom: bottomLen <= 18 ? 64 : bottomLen <= 24 ? 54 : bottomLen <= 30 ? 46 : 40,
  };
}

interface HeaderRenderProps {
  headerTop: string;
  headerBottom: string;
  uiBreaking: string;
  colors: Colors;
  entrance: number;  // spring 0..1
}

function HeaderBannerFlat({headerTop, headerBottom, colors, entrance, uiBreaking}: HeaderRenderProps) {
  const sizes = headerFontSizes(headerTop.length, headerBottom.length);
  const translate = interpolate(entrance, [0, 1], [-40, 0]);
  return (
    <>
      <div style={badgeStyle(colors.primary, '#fff')}>{uiBreaking}</div>
      <div
        style={{
          background: `linear-gradient(90deg, ${colors.primary}, ${shiftLighter(colors.primary)})`,
          padding: '78px 60px 44px',
          textAlign: 'center',
          fontWeight: 900,
          lineHeight: 1.02,
          letterSpacing: 0.5,
          color: '#fff',
          boxShadow: '0 10px 0 rgba(0,0,0,.4)',
          opacity: entrance,
          transform: `translateY(${translate}px)`,
        }}
      >
        <span style={{display: 'block', whiteSpace: 'nowrap', fontSize: sizes.top}}>{headerTop}</span>
        <span style={{display: 'block', whiteSpace: 'nowrap', marginTop: 8, fontSize: sizes.bottom}}>
          {headerBottom}
        </span>
      </div>
    </>
  );
}

function HeaderBannerSkewed({headerTop, headerBottom, colors, entrance, uiBreaking}: HeaderRenderProps) {
  const sizes = {
    top: headerTop.length <= 10 ? 150 : headerTop.length <= 14 ? 120 : headerTop.length <= 20 ? 95 : 75,
    bottom: headerBottom.length <= 16 ? 56 : headerBottom.length <= 22 ? 46 : 38,
  };
  const translate = interpolate(entrance, [0, 1], [-60, 0]);
  return (
    <>
      <div style={badgeStyle(colors.accent, colors.primary)}>{uiBreaking}</div>
      <div
        style={{
          background: `linear-gradient(135deg, ${colors.primary}, ${colors.bgGrad2})`,
          padding: '50px 40px 40px',
          textAlign: 'center',
          fontFamily: "'Oswald', Impact, sans-serif",
          color: colors.accent,
          borderBottom: `8px solid ${colors.accent}`,
          opacity: entrance,
          transform: `translateY(${translate}px)`,
        }}
      >
        <span
          style={{
            display: 'block',
            fontSize: sizes.top,
            lineHeight: 0.95,
            letterSpacing: sizes.top >= 120 ? 6 : 4,
            textShadow: '6px 6px 0 #000',
            WebkitTextStroke: '2px #000',
            whiteSpace: 'nowrap',
          }}
        >
          {headerTop}
        </span>
        <span
          style={{
            display: 'block',
            fontSize: sizes.bottom,
            color: colors.textMain,
            letterSpacing: 4,
            marginTop: 14,
            whiteSpace: 'nowrap',
          }}
        >
          {headerBottom}
        </span>
      </div>
    </>
  );
}

function HeaderHeroOverlay({headerTop, headerBottom, colors, entrance, uiBreaking}: HeaderRenderProps) {
  // No background panel — headline sits ON the photo. Tight chip + bold text.
  const sizes = headerFontSizes(headerTop.length, headerBottom.length);
  return (
    <>
      <div style={{...badgeStyle(colors.accent, '#000'), top: 24, right: 24}}>{uiBreaking}</div>
      <div
        style={{
          position: 'absolute',
          top: 60,
          left: 40,
          right: 40,
          textAlign: 'left',
          fontWeight: 900,
          letterSpacing: 0.4,
          color: colors.accent,
          textShadow: '0 4px 16px rgba(0,0,0,.7)',
          opacity: entrance,
          transform: `translateY(${interpolate(entrance, [0, 1], [20, 0])}px)`,
          zIndex: 25,
        }}
      >
        <div style={{fontSize: sizes.top, lineHeight: 1, whiteSpace: 'nowrap'}}>{headerTop}</div>
        <div
          style={{
            fontSize: sizes.bottom * 0.85,
            color: '#fff',
            opacity: 0.95,
            marginTop: 6,
            whiteSpace: 'nowrap',
          }}
        >
          {headerBottom}
        </div>
      </div>
    </>
  );
}

// ─── Photo sub-renderers ───────────────────────────────────────────────────

interface PhotoRenderProps {
  bgImageUrl: string;
  photoOverlay: string;
  category: string;
  colors: Colors;
  entrance: number;
  /** When true, headerStyle is hero-overlay → photo extends to top of frame */
  fillTop?: boolean;
}

function PhotoFullBleed({bgImageUrl, photoOverlay, category, colors, entrance, fillTop}: PhotoRenderProps) {
  const slideX = interpolate(entrance, [0, 1], [-200, 0]);
  return (
    <div
      style={{
        position: 'relative',
        height: fillTop ? 900 : 640,
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
      {category && (
        <div
          style={{
            position: 'absolute',
            top: 30,
            left: 30,
            background: 'rgba(0,0,0,.78)',
            color: '#fff',
            fontSize: 26,
            fontWeight: 700,
            padding: '6px 14px',
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
            color: '#000',
            fontSize: 36,
            fontWeight: 900,
            padding: '14px 20px',
            textAlign: 'center',
            transform: `translateX(${slideX}px)`,
          }}
        >
          {photoOverlay}
        </div>
      )}
    </div>
  );
}

function PhotoBanded({bgImageUrl, photoOverlay, category, colors, entrance}: PhotoRenderProps) {
  // Smaller photo, no fullscreen overlay text — saves room for body.
  return (
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
            filter: 'brightness(0.85)',
          }}
        />
      )}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,.6) 100%)',
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
            opacity: entrance,
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
            fontSize: 32,
            fontWeight: 900,
            padding: '12px 18px',
            textAlign: 'center',
            opacity: entrance,
          }}
        >
          {photoOverlay}
        </div>
      )}
    </div>
  );
}

function PhotoBlurBg({bgImageUrl, photoOverlay, category, colors}: PhotoRenderProps) {
  // No photo band — image blurred fullscreen behind everything else.
  return (
    <>
      {bgImageUrl && (
        <AbsoluteFill
          style={{
            backgroundImage: `url(${bgImageUrl})`,
            backgroundSize: 'cover',
            backgroundPosition: 'center',
            opacity: 0.25,
            filter: 'blur(8px)',
          }}
        />
      )}
      {category && (
        <div
          style={{
            position: 'absolute',
            top: 240,
            left: 40,
            background: 'rgba(0,0,0,.8)',
            color: colors.accent,
            fontSize: 22,
            padding: '6px 12px',
            letterSpacing: 2,
            zIndex: 8,
          }}
        >
          {category}
        </div>
      )}
    </>
  );
}

// ─── Body sub-renderers ────────────────────────────────────────────────────

interface BodyRenderProps {
  bodyParagraph: string;
  photoOverlay: string;
  colors: Colors;
  entrance: number;
  frame: number;
  fps: number;
}

function bodyParagraphFontSize(len: number): number {
  if (len < 220) return 46;
  if (len < 360) return 40;
  if (len < 500) return 36;
  return 32;
}

function BodyParagraph({bodyParagraph, colors, entrance}: BodyRenderProps) {
  const size = bodyParagraphFontSize(bodyParagraph.length);
  return (
    <div
      style={{
        flex: 1,
        padding: '40px 60px 200px',
        opacity: entrance,
        transform: `translateY(${interpolate(entrance, [0, 1], [40, 0])}px)`,
      }}
    >
      <div
        style={{
          fontSize: size,
          lineHeight: 1.4,
          fontWeight: 600,
          color: colors.textMain,
        }}
      >
        {bodyParagraph}
      </div>
    </div>
  );
}

function BodyQuote({bodyParagraph, colors, entrance}: BodyRenderProps) {
  // Pull-quote style — first sentence rendered big, rest as caption.
  const split = splitQuoteCaption(bodyParagraph);
  const quoteSize = split.quote.length <= 80 ? 56
                  : split.quote.length <= 140 ? 46 : 38;
  return (
    <div
      style={{
        flex: 1,
        padding: '40px 60px 200px',
        opacity: entrance,
        transform: `translateY(${interpolate(entrance, [0, 1], [30, 0])}px)`,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
      }}
    >
      <div style={{fontSize: 120, lineHeight: 0.7, color: colors.accent, opacity: 0.55}}>“</div>
      <div
        style={{
          fontSize: quoteSize,
          lineHeight: 1.25,
          fontWeight: 800,
          color: '#fff',
          paddingLeft: 14,
          marginTop: -10,
        }}
      >
        {split.quote}
      </div>
      {split.caption && (
        <div
          style={{
            marginTop: 20,
            fontSize: 28,
            color: colors.textMuted,
            paddingLeft: 14,
          }}
        >
          {split.caption}
        </div>
      )}
    </div>
  );
}

function BodyStatHero({bodyParagraph, colors, entrance, frame, fps}: BodyRenderProps) {
  const {number, caption} = extractStat(bodyParagraph);
  const target = parseTargetNumber(number);
  const countDuration = Math.round(fps * 1.2);
  const countProgress = interpolate(frame, [0, countDuration], [0, 1], {
    extrapolateRight: 'clamp',
  });
  let display = number;
  if (target !== null) {
    const isPercent = number.startsWith('%');
    const hasDecimal = number.includes(',');
    const eased = 1 - Math.pow(1 - countProgress, 3);
    const cur = target * eased;
    const v = hasDecimal ? cur.toFixed(1).replace('.', ',') : Math.round(cur).toString();
    display = isPercent ? `%${v}` : v;
  }
  return (
    <div
      style={{
        flex: 1,
        padding: '20px 60px 200px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        opacity: entrance,
      }}
    >
      <div
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 800,
          fontSize: number === '◆' ? 60 : 240,
          lineHeight: 0.95,
          color: number === '◆' ? colors.textMuted : colors.accent,
          letterSpacing: -4,
          textShadow: number === '◆' ? 'none' : '0 4px 24px rgba(0,0,0,0.4)',
          whiteSpace: 'nowrap',
          marginBottom: 16,
        }}
      >
        {display}
      </div>
      <div
        style={{
          fontSize: 32,
          lineHeight: 1.35,
          fontWeight: 500,
          color: '#fff',
        }}
      >
        {caption || bodyParagraph}
      </div>
    </div>
  );
}

// ─── Shared helpers ────────────────────────────────────────────────────────

function shiftLighter(hex: string): string {
  // Subtle horizontal-gradient endpoint — same trick as NewscastBasic.
  const m = hex.replace('#', '');
  const r = parseInt(m.slice(0, 2), 16);
  const g = parseInt(m.slice(2, 4), 16);
  const b = parseInt(m.slice(4, 6), 16);
  const mix = (c: number) => Math.min(255, Math.round(c + (255 - c) * 0.25));
  return `#${[mix(r), mix(g), mix(b)].map((c) => c.toString(16).padStart(2, '0')).join('')}`;
}

function badgeStyle(bg: string, color: string): React.CSSProperties {
  return {
    position: 'absolute',
    top: 14,
    right: 14,
    background: bg,
    color,
    fontSize: 20,
    fontWeight: 800,
    letterSpacing: 1.5,
    padding: '6px 14px',
    borderRadius: 4,
    zIndex: 30,
  };
}

function splitQuoteCaption(text: string): {quote: string; caption: string} {
  // First sentence becomes the quote, rest becomes caption.
  const m = text.match(/^([^.!?]+[.!?])\s*(.*)$/);
  if (m && m[1].length > 30) return {quote: m[1].trim(), caption: m[2].trim()};
  return {quote: text, caption: ''};
}

function extractStat(text: string): {number: string; caption: string} {
  let m = text.match(/y[üu]zde\s+(\d{1,3}(?:[,.]\d+)?)/i);
  if (m) return {number: '%' + m[1].replace('.', ','), caption: strip(text, m[0])};
  m = text.match(/%\s*(\d{1,3}(?:[,.]\d+)?)/);
  if (m) return {number: '%' + m[1].replace('.', ','), caption: strip(text, m[0])};
  m = text.match(/([₺$€£]\s*\d+(?:[,.]\d+)?(?:\s*(?:milyon|milyar|bin))?)/i);
  if (m) return {number: m[1].replace(/\s+/g, ' ').trim(), caption: strip(text, m[0])};
  m = text.match(/(\b\d{1,3}(?:[.,]\d{3})+\b|\b\d{3,}\b)(?:\s*(milyon|milyar|bin))?/i);
  if (m) return {number: m[1] + (m[2] ? ' ' + m[2] : ''), caption: strip(text, m[0])};
  return {number: '◆', caption: text};
}

function strip(text: string, match: string): string {
  return text.replace(match, '').replace(/\s+/g, ' ').replace(/^[\s,.;:]+/, '').trim();
}

function parseTargetNumber(stat: string): number | null {
  const pct = stat.match(/^%([\d,.]+)$/);
  if (pct) return parseFloat(pct[1].replace(',', '.'));
  const plain = stat.match(/^([\d,.]+)$/);
  if (plain) return parseFloat(plain[1].replace(/\./g, '').replace(',', '.'));
  return null;
}

// ─── Main composition ─────────────────────────────────────────────────────

export const Adaptive: React.FC<AdaptiveProps> = ({
  headerTop, headerBottom, photoOverlay, bodyParagraph,
  category, handle, bgImageUrl, uiBreaking, colors, dimensions,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  const headerEntrance = spring({
    frame, fps,
    config: {damping: 200, stiffness: 220},
    durationInFrames: Math.round(fps * 0.4),
  });
  const photoEntrance = spring({
    frame: frame - Math.round(fps * 0.15), fps,
    config: {damping: 200, stiffness: 180},
    durationInFrames: Math.round(fps * 0.5),
  });
  const bodyEntrance = spring({
    frame: frame - Math.round(fps * 0.3), fps,
    config: {damping: 200, stiffness: 180},
    durationInFrames: Math.round(fps * 0.6),
  });

  const progress = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateRight: 'clamp',
  });

  const headerCommon: HeaderRenderProps = {
    headerTop, headerBottom, uiBreaking, colors, entrance: headerEntrance,
  };
  const photoCommon: PhotoRenderProps = {
    bgImageUrl, photoOverlay, category, colors, entrance: photoEntrance,
    fillTop: dimensions.headerStyle === 'hero-overlay',
  };
  const bodyCommon: BodyRenderProps = {
    bodyParagraph, photoOverlay, colors, entrance: bodyEntrance, frame, fps,
  };

  // hero-overlay header sits ON the photo — render photo first, then header on top
  const heroOverlayMode = dimensions.headerStyle === 'hero-overlay';

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, ${colors.bgGrad1}, ${colors.bgGrad2})`,
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        color: colors.textMain,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* When blur-bg is selected, the image fills the entire frame underneath everything */}
      {dimensions.photoTreatment === 'blur-bg' && <PhotoBlurBg {...photoCommon} />}

      {/* Order: header → photo → body — unless hero-overlay (photo first, header floats over) */}
      {!heroOverlayMode && (() => {
        if (dimensions.headerStyle === 'banner-flat')   return <HeaderBannerFlat {...headerCommon} />;
        if (dimensions.headerStyle === 'banner-skewed') return <HeaderBannerSkewed {...headerCommon} />;
        return null;
      })()}

      {dimensions.photoTreatment !== 'blur-bg' && (() => {
        if (dimensions.photoTreatment === 'full-bleed') return <PhotoFullBleed {...photoCommon} />;
        if (dimensions.photoTreatment === 'banded')     return <PhotoBanded {...photoCommon} />;
        return null;
      })()}

      {heroOverlayMode && <HeaderHeroOverlay {...headerCommon} />}

      {(() => {
        if (dimensions.bodyStyle === 'paragraph') return <BodyParagraph {...bodyCommon} />;
        if (dimensions.bodyStyle === 'quote')     return <BodyQuote {...bodyCommon} />;
        if (dimensions.bodyStyle === 'stat-hero') return <BodyStatHero {...bodyCommon} />;
        return null;
      })()}

      {/* Progress bar + handle (shared chrome across all dimension combos) */}
      <div
        style={{
          position: 'absolute',
          left: 0, right: 0, bottom: 84,
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
      <div
        style={{
          position: 'absolute',
          left: 0, right: 0, bottom: 32,
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
