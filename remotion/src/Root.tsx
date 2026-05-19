import React from 'react';
import {Composition} from 'remotion';
import {
  NewscastBasic,
  newscastSchema,
  NEWSCAST_DEFAULTS,
} from './templates/NewscastBasic';
import {
  StadiumBasic,
  stadiumSchema,
  STADIUM_DEFAULTS,
} from './templates/StadiumBasic';
import {StatHero, statHeroSchema, STAT_HERO_DEFAULTS} from './templates/StatHero';
import {BigQuote, bigQuoteSchema, BIG_QUOTE_DEFAULTS} from './templates/BigQuote';
import {Adaptive, adaptiveSchema, ADAPTIVE_DEFAULTS} from './templates/Adaptive';

// 1080×1920 (YouTube Shorts), 30 fps. duration in frames = duration_s * 30.
// calculateMetadata lets the Python wrapper override durationSeconds at
// render time via --props=, so the same template serves 6s or 30s shorts.
const WIDTH = 1080;
const HEIGHT = 1920;
const FPS = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="newscast-basic"
        component={NewscastBasic}
        durationInFrames={NEWSCAST_DEFAULTS.durationSeconds * FPS}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        schema={newscastSchema}
        defaultProps={NEWSCAST_DEFAULTS}
        calculateMetadata={({props}) => ({
          durationInFrames: Math.max(1, Math.round((props.durationSeconds ?? 6) * FPS)),
        })}
      />
      <Composition
        id="stadium-basic"
        component={StadiumBasic}
        durationInFrames={STADIUM_DEFAULTS.durationSeconds * FPS}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        schema={stadiumSchema}
        defaultProps={STADIUM_DEFAULTS}
        calculateMetadata={({props}) => ({
          durationInFrames: Math.max(1, Math.round((props.durationSeconds ?? 6) * FPS)),
        })}
      />
      <Composition
        id="stat-hero"
        component={StatHero}
        durationInFrames={STAT_HERO_DEFAULTS.durationSeconds * FPS}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        schema={statHeroSchema}
        defaultProps={STAT_HERO_DEFAULTS}
        calculateMetadata={({props}) => ({
          durationInFrames: Math.max(1, Math.round((props.durationSeconds ?? 6) * FPS)),
        })}
      />
      <Composition
        id="big-quote"
        component={BigQuote}
        durationInFrames={BIG_QUOTE_DEFAULTS.durationSeconds * FPS}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        schema={bigQuoteSchema}
        defaultProps={BIG_QUOTE_DEFAULTS}
        calculateMetadata={({props}) => ({
          durationInFrames: Math.max(1, Math.round((props.durationSeconds ?? 6) * FPS)),
        })}
      />
      <Composition
        id="adaptive"
        component={Adaptive}
        durationInFrames={ADAPTIVE_DEFAULTS.durationSeconds * FPS}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        schema={adaptiveSchema}
        defaultProps={ADAPTIVE_DEFAULTS}
        calculateMetadata={({props}) => ({
          durationInFrames: Math.max(1, Math.round((props.durationSeconds ?? 6) * FPS)),
        })}
      />
    </>
  );
};
