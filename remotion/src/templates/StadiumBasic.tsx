/**
 * StadiumBasic — Remotion port of the HTML stadium template.
 *
 * Sports-broadcast energy: huge Oswald headline up top, skewed accent
 * banner on the photo, body text on a dark sports gradient. Animations:
 *   - Header text drops in from above (snappy spring)
 *   - Yellow banner slides in from the left (skewed entrance)
 *   - Body fades up after a beat
 *   - Progress bar is frame-counted (not CSS animation)
 *
 * Visual parity goal: a viewer should not notice this is a different
 * renderer from the HTML version. Once verified, opt-in via channel
 * config swaps the pipeline path with no content changes.
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

export const stadiumSchema = z.object({
  headerTop: z.string().min(1).max(60),
  headerBottom: z.string().min(1).max(80),
  photoOverlay: z.string().max(140).default(''),
  bodyParagraph: z.string().min(1).max(800),
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
      primary: '#a30d2d',
      accent: '#ffb81c',
      bgGrad1: '#1a8b3a',
      bgGrad2: '#0a4d1a',
      textMain: '#fff8e7',
      textMuted: '#e8c56a',
    }),
});

export type StadiumProps = z.infer<typeof stadiumSchema>;

export const STADIUM_DEFAULTS: StadiumProps = {
  headerTop: 'GS 3-0 FB',
  headerBottom: 'DERBİ FİNALİ',
  photoOverlay: 'CIMBOM ŞAMPİYON',
  bodyParagraph:
    'Galatasaray derbi maçında Fenerbahçe karşısında 3-0 galip geldi. ' +
    'Aslanlar ligin son haftasını şampiyonluk havasında geçti.',
  handle: '@galatasaray',
  durationSeconds: 6,
  bgImageUrl: '',
  uiBreaking: 'SON DAKİKA',
  colors: {
    primary: '#a30d2d',
    accent: '#ffb81c',
    bgGrad1: '#1a8b3a',
    bgGrad2: '#0a4d1a',
    textMain: '#fff8e7',
    textMuted: '#e8c56a',
  },
};

export const StadiumBasic: React.FC<StadiumProps> = ({
  headerTop,
  headerBottom,
  photoOverlay,
  bodyParagraph,
  handle,
  bgImageUrl,
  uiBreaking,
  colors,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  // Header drops in from above (sports broadcast style — punchy entrance)
  const headerEntrance = spring({
    frame,
    fps,
    config: {damping: 180, stiffness: 200},
    durationInFrames: Math.round(fps * 0.5),
  });
  const headerTranslateY = interpolate(headerEntrance, [0, 1], [-80, 0]);

  // Yellow banner slides in from left after a beat
  const bannerDelay = Math.round(fps * 0.25);
  const bannerEntrance = spring({
    frame: frame - bannerDelay,
    fps,
    config: {damping: 200, stiffness: 240},
    durationInFrames: Math.round(fps * 0.5),
  });
  const bannerTranslateX = interpolate(bannerEntrance, [0, 1], [-300, 0]);
  const bannerOpacity = bannerEntrance;

  // Body fades up after header + banner are in place
  const bodyDelay = Math.round(fps * 0.55);
  const bodyEntrance = spring({
    frame: frame - bodyDelay,
    fps,
    config: {damping: 200, stiffness: 180},
    durationInFrames: Math.round(fps * 0.6),
  });
  const bodyOpacity = bodyEntrance;
  const bodyTranslateY = interpolate(bodyEntrance, [0, 1], [30, 0]);

  // Progress bar driven by the actual frame counter
  const progress = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateRight: 'clamp',
  });

  // Body text auto-shrink heuristic: roughly emulates the auto-fit script
  // in the HTML template. Below ~250 chars → max 68px; ~500 chars → 48px;
  // longer → 38px (min).
  const bodyLen = bodyParagraph.length;
  const bodyFontSize =
    bodyLen < 220 ? 68 : bodyLen < 360 ? 58 : bodyLen < 500 ? 50 : 42;

  // Oswald header font auto-scale — letterSpacing 8px at 180px font means
  // ~110px per char. 1080 wide minus 80px padding = 1000px content; ~9 chars
  // fit at full size. Turkish headlines often exceed that ("TRANSFER BOMBASI").
  const topLen = headerTop.length;
  const topFontSize = topLen <= 9 ? 180
                    : topLen <= 12 ? 150
                    : topLen <= 16 ? 120
                    : topLen <= 22 ? 95
                    : 75;
  const bottomLen = headerBottom.length;
  const bottomFontSize = bottomLen <= 14 ? 60
                       : bottomLen <= 20 ? 50
                       : bottomLen <= 28 ? 44
                       : 38;

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, #0a1a0a, #000000)`,
        fontFamily:
          "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        color: colors.textMain,
      }}
    >
      {/* Stage badge */}
      <div
        style={{
          position: 'absolute',
          top: 16,
          right: 16,
          background: colors.accent,
          color: colors.primary,
          fontFamily: "'Oswald', Impact, sans-serif",
          fontSize: 22,
          fontWeight: 700,
          letterSpacing: 2,
          padding: '5px 12px',
          zIndex: 10,
        }}
      >
        {uiBreaking}
      </div>

      {/* Header — big Oswald top + small bot, dropped-in entrance */}
      <div
        style={{
          background: `linear-gradient(135deg, ${colors.primary}, ${colors.bgGrad2})`,
          padding: '50px 40px 40px',
          textAlign: 'center',
          fontFamily: "'Oswald', Impact, sans-serif",
          color: colors.accent,
          borderBottom: `8px solid ${colors.accent}`,
          opacity: headerEntrance,
          transform: `translateY(${headerTranslateY}px)`,
        }}
      >
        <span
          style={{
            display: 'block',
            fontSize: topFontSize,
            lineHeight: 0.95,
            letterSpacing: topFontSize >= 150 ? 8 : topFontSize >= 120 ? 6 : 4,
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
            fontSize: bottomFontSize,
            color: colors.textMain,
            letterSpacing: bottomFontSize >= 50 ? 6 : 4,
            marginTop: 14,
            whiteSpace: 'nowrap',
          }}
        >
          {headerBottom}
        </span>
      </div>

      {/* Photo band */}
      <div
        style={{
          position: 'relative',
          height: 580,
          background: `linear-gradient(180deg, ${colors.bgGrad1}, ${colors.bgGrad2})`,
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
              'linear-gradient(180deg, transparent 60%, rgba(0,0,0,.8))',
          }}
        />
        {photoOverlay && (
          <div
            style={{
              position: 'absolute',
              bottom: 30,
              left: 30,
              right: 30,
              background: colors.accent,
              color: colors.primary,
              fontFamily: "'Oswald', Impact, sans-serif",
              padding: '22px 30px',
              fontSize: 64,
              textAlign: 'center',
              letterSpacing: 2,
              transform: `translateX(${bannerTranslateX}px) skewX(-10deg)`,
              boxShadow: '0 8px 0 #000',
              opacity: bannerOpacity,
              zIndex: 1,
            }}
          >
            {photoOverlay}
          </div>
        )}
      </div>

      {/* Body — centered with sport gradient backdrop, fades up */}
      <div
        style={{
          flex: 1,
          marginBottom: 60,
          padding: '28px 44px 24px',
          display: 'grid',
          placeItems: 'center',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: '100%',
            fontSize: bodyFontSize,
            lineHeight: 1.32,
            fontWeight: 600,
            opacity: bodyOpacity,
            transform: `translateY(${bodyTranslateY}px)`,
            display: '-webkit-box',
            WebkitLineClamp: 9,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
            maskImage:
              'linear-gradient(180deg, #000 0%, #000 92%, transparent 100%)',
            WebkitMaskImage:
              'linear-gradient(180deg, #000 0%, #000 92%, transparent 100%)',
            textAlign: 'center',
          }}
        >
          {bodyParagraph}
        </div>
      </div>

      {/* Progress bar — frame-counted */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 84,
          height: 8,
          background: 'rgba(255,255,255,.15)',
        }}
      >
        <div
          style={{
            width: `${progress}%`,
            height: '100%',
            background: colors.accent,
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
          color: colors.accent,
          fontFamily: "'Oswald', Impact, sans-serif",
          fontSize: 32,
          letterSpacing: 4,
        }}
      >
        {handle}
      </div>
    </AbsoluteFill>
  );
};
