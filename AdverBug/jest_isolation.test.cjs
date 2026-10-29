const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const records = JSON.parse(fs.readFileSync('/dataset.json', 'utf8'));
const moduleCache = new Map();

function runtimeSource(srcFile) {
  if (process.env.ADVERBUG_SOURCE_MODE !== 'lib') {
    return srcFile;
  }
  return srcFile.replace(/^src\//, 'lib/');
}

async function loadModule(srcFile) {
  const runtimeFile = runtimeSource(srcFile);
  if (!moduleCache.has(runtimeFile)) {
    const absolute = path.join('/testbed', runtimeFile);
    moduleCache.set(runtimeFile, import(pathToFileURL(absolute).href));
  }
  return moduleCache.get(runtimeFile);
}

function namedExport(moduleNamespace, name) {
  return moduleNamespace[name] ?? moduleNamespace.default?.[name];
}

describe('AdverBug dataset targets remain testable without original tests', () => {
  test.each(records.map((record, index) => [
    `${index + 1}: ${record.src_file} :: ${record.class_name ? `${record.class_name}.` : ''}${record.member_name || record.name}`,
    record,
  ]))('%s', async (_label, record) => {
    const moduleNamespace = await loadModule(record.src_file);

    if (record.class_name) {
      const className = record.class_exported_name || record.class_name;
      const TargetClass = record.class_export_kind === 'esm_default'
        ? moduleNamespace.default
        : namedExport(moduleNamespace, className);
      expect(typeof TargetClass).toBe('function');

      const methodName = record.member_name || record.name;
      const method = TargetClass.prototype?.[methodName] || TargetClass[methodName];
      expect(typeof method).toBe('function');
      return;
    }

    const exportName = record.exported_name || record.name;
    const target = ['esm_default', 'commonjs_default'].includes(record.export_kind)
      ? moduleNamespace.default
      : namedExport(moduleNamespace, exportName);
    expect(typeof target).toBe('function');
  });
});
