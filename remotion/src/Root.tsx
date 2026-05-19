import React from 'react';
import {Composition} from 'remotion';
import {NewscastBasic, newscastSchema, NewscastProps, NEWSCAST_DEFAULTS}
  from './templates/NewscastBasic';

// 1080×1920 (YouTube Shorts), 30 fps. duration in frames = duration_s * 30.
// Default 6s = 180 frames; the Python wrapper overrides via --props at render
// time when channels use longer/shorter durations.
const WIDTH = 1080;
const HEIGHT = 1920;
const FPS = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="newscast-basic"
        component={NewscastBasic}
        durationInFrames={6 * FPS}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        schema={newscastSchema}
        defaultProps={NEWSCAST_DEFAULTS}
        calculateMetadata={({props}) => {
          const seconds = props.durationSeconds ?? 6;
          return {durationInFrames: Math.max(1, Math.round(seconds * FPS))};
        }}
      />
    </>
  );
};
