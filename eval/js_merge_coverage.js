#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const [manifestPath, outputPath] = process.argv.slice(2);
if (!manifestPath || !outputPath) {
  console.error('Usage: js_merge_coverage.js <manifest.json> <coverage-final.json>');
  process.exit(2);
}

const searchPaths = [
  '/testbed/node_modules',
  '/testbed/.adverbug_jest_runtime/node_modules',
];
let libraryPath;
try {
  libraryPath = require.resolve('istanbul-lib-coverage', { paths: searchPaths });
} catch (error) {
  console.error(`istanbul-lib-coverage is unavailable: ${error.message}`);
  process.exit(3);
}

const libCoverage = require(libraryPath);
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
if (!Array.isArray(manifest.inputs)) {
  throw new TypeError('Coverage merge manifest must contain an inputs array');
}

const coverageMap = libCoverage.createCoverageMap({});
for (const input of manifest.inputs) {
  const report = JSON.parse(fs.readFileSync(input, 'utf8'));
  coverageMap.merge(report);
}

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(coverageMap.toJSON(), null, 2)}\n`);
fs.chmodSync(outputPath, 0o666);

let version = null;
try {
  const packagePath = path.join(path.dirname(libraryPath), 'package.json');
  version = JSON.parse(fs.readFileSync(packagePath, 'utf8')).version || null;
} catch (_) {
  // The resolved library is authoritative even if package metadata is hidden.
}

console.log(JSON.stringify({
  merger: 'istanbul-lib-coverage',
  version,
  inputCount: manifest.inputs.length,
  fileCount: coverageMap.files().length,
}));
