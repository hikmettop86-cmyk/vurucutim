const log = require('electron-log/main');
const path = require('node:path');
const paths = require('./paths');

log.initialize();
log.transports.file.resolvePathFn = () => path.join(paths.logsDir(), 'electron-main.log');
log.transports.file.maxSize = 5 * 1024 * 1024;   // 5MB
log.transports.console.level = process.env.NODE_ENV === 'production' ? 'info' : 'debug';

module.exports = log;
