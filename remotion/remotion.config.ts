import {Config} from '@remotion/cli/config';

// Match our 9:16 YouTube Shorts output. Concurrency 1 keeps memory predictable
// when invoked as a subprocess from the Python pipeline (which may render
// multiple channels in parallel).
Config.setVideoImageFormat('jpeg');
Config.setConcurrency(1);
Config.setOverwriteOutput(true);
