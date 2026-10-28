// Build only reviewed committed public files, never a checkout or member uploads.
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdir, readdir, readFile, writeFile} from 'node:fs/promises';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const repo = join(root, '../..');
const config = JSON.parse(await readFile(join(root, 'asset-release.json'), 'utf8'));
const revisions = [...new Set([config.revision, ...(config.retainedRevisions || [])])];
const allowed = /^(?:[\w-]+\.(?:css|js)|fonts\/[\w-]+\.woff2|fonts\/(?:Lato|NotoSansKR)-OFL\.txt|og\/club-preview\.png)$/;
const metadata = new Set(['fonts/PROVENANCE.txt', 'fonts/font-provenance.json']);
const sha = content => createHash('sha256').update(content).digest('hex');
const git = (...args) => execFileSync('git', args, {cwd: repo, windowsHide: true, maxBuffer: 16 * 1024 * 1024});
const output = new Map();
let currentManifest;
for (const revision of revisions) {
  if (!/^[a-f0-9]{40}$/.test(revision)) throw new Error('Select exact server commits');
  const tree = git('ls-tree', '-r', '-z', revision, '--', 'static').toString().split('\0').filter(Boolean);
  const files = {};
  const contents = new Map();
  for (const entry of tree) {
    const [info, path] = entry.split('\t');
    const name = path.slice('static/'.length);
    if (metadata.has(name)) continue;
    if (!info.startsWith('100644 blob ') || !allowed.test(name)) throw new Error('Review unexpected static entry: ' + path);
    const content = git('show', revision + ':' + path);
    files[name] = {sha256: sha(content), bytes: content.length};
    contents.set(name, content);
  }
  if (!contents.size) throw new Error('No reviewed assets found');
  // Version CSS and its relative font/import dependencies together.
  const digest = sha(Object.keys(files).sort().map(name => name + '\0' + files[name].sha256 + '\n').join(''));
  const manifest = {schema: 1, revision, digest, prefix: '_v/' + digest, files};
  for (const [name, content] of contents) output.set('static/' + manifest.prefix + '/' + name, content);
  if (revision === config.revision) currentManifest = manifest;
}
const headers = `/static/_v/*
  Cache-Control: public, max-age=31536000, immutable
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  ! Set-Cookie
  ! X-App-Origin-Auth
`;
async function existingFiles(directory, prefix = '') {
  let entries;
  try { entries = await readdir(directory, {withFileTypes: true}); }
  catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  const result = [];
  for (const entry of entries) {
    if (entry.isSymbolicLink()) throw new Error('Staging must not contain symlinks');
    const relative = prefix + entry.name;
    if (entry.isDirectory()) result.push(...await existingFiles(join(directory, entry.name), relative + '/'));
    else result.push(relative);
  }
  return result;
}
async function stage(directory, entries) {
  const expected = new Set(entries.keys());
  if ((await existingFiles(directory)).some(path => !expected.has(path))) {
    throw new Error('Unexpected staged file; inspect before clearing directory: ' + directory);
  }
  for (const [path, content] of entries) {
    const destination = join(directory, path);
    if (path.startsWith('static/_v/')) {
      try {
        if (!(await readFile(destination)).equals(content)) throw new Error('Immutable asset differs: ' + path);
      } catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
    await mkdir(dirname(destination), {recursive: true});
    await writeFile(destination, content);
  }
}
// Separate outputs avoid publishing any older, unversioned staging files.
await stage(join(root, '.versioned-assets'), new Map([...output, ['_headers', headers]]));
await stage(join(root, '.server-assets'), new Map([...output, ['asset-manifest.json', JSON.stringify(currentManifest, null, 2) + '\n']]));
console.log(JSON.stringify({revision: config.revision, digest: currentManifest.digest,
  currentFiles: Object.keys(currentManifest.files).length, publishedFiles: output.size,
  bytes: [...output.values()].reduce((sum, value) => sum + value.length, 0)}));
