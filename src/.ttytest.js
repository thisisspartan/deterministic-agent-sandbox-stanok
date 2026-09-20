'use strict';
// TEMP: fake a TTY stdout and start the animation via the exported run().
Object.defineProperty(process.stdout, 'isTTY', { value: true, configurable: true });
process.stdout.columns = 80;
process.stdout.rows = 24;
require('./fire.js').run();
