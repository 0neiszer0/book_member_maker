// Publish only committed public assets from the selected running server release.
// This deliberately excludes another session's edits and untracked local files.
import {execFileSync} from 'node:child_process';
import {mkdir, readdir, readFile, writeFile} from 'node:fs/promises';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const {revision} = JSON.parse(await readFile(join(root, 'asset-release.json'), 'utf8'));
if (!/^[a-f0-9]{40}$/.test(revision)) throw new Error('Select an exact server commit first');
const git = (...args) => execFileSync('git', args, {cwd: root, windowsHide: true});
const files = git('ls-tree', '-r', '--name-only', '-z', revision, '--', '../../static')
  .toString('utf8').split('\0').filter(Boolean).map(path => path.replace(/^\.\.\/\.\.\//, ''));
if (!files.length || files.some(path => !/^static\/(?:[\w-]+\.(?:css|js)|og\/club-preview\.png)$/.test(path))) {
  throw new Error('Review the public asset list before adding other file types or paths');
}
const output = join(root, '.assets');
async function existingFiles(directory, prefix = '') {
  let entries;
  try { entries = await readdir(directory, {withFileTypes: true}); }
  catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  const result = [];
  for (const entry of entries) {
    const relative = prefix + entry.name;
    if (entry.isSymbolicLink()) throw new Error('Asset staging must not contain symlinks');
    if (entry.isDirectory()) result.push(...await existingFiles(join(directory, entry.name), relative + '/'));
    else result.push(relative);
  }
  return result;
}
if ((await existingFiles(output)).some(path => !files.includes(path))) {
  throw new Error('Unexpected staged asset: inspect and clean the staging directory before deployment');
}
let bytes = 0;
for (const path of files) {
  const content = git('show', revision + ':' + path);
  await mkdir(dirname(join(output, path)), {recursive: true});
  await writeFile(join(output, path), content);
  bytes += content.length;
}
console.log(JSON.stringify({assetRevision: revision, files: files.length, bytes}));
