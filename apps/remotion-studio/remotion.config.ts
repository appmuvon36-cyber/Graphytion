import {Config} from '@remotion/cli/config';

// CPU-safe defaults for Graphytion's Linux render-worker containers.
Config.setChromiumOpenGlRenderer('swangle');
Config.setConcurrency(2);
Config.setOverwriteOutput(true);
