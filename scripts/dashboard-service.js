const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const crypto = require('node:crypto');

const projectRoot = path.resolve(__dirname, '..');
const dashboardRoot = path.join(projectRoot, 'apps', 'dashboard');
const runtimeRoot = path.join(projectRoot, '.runtime');
const pid = process.pid;
const instanceId = crypto.randomBytes(32).toString('hex');
const identityPath = path.join(runtimeRoot, `service-identity-dashboard-${pid}.json`);
const stopPath = path.join(runtimeRoot, `service-stop-dashboard-${pid}.json`);
const identity = {
  pid,
  service: 'dashboard',
  checkout_root: projectRoot,
  instance_id: instanceId,
};

function atomicJson(filePath, value) {
  const tempPath = `${filePath}.${crypto.randomBytes(8).toString('hex')}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify(value), { encoding: 'utf8', flag: 'wx' });
  fs.renameSync(tempPath, filePath);
}

async function main() {
  fs.mkdirSync(runtimeRoot, { recursive: true });
  const normalizePath = (value) => path.resolve(value).replace(/^\\\\\?\\/, '').toLowerCase();
  if (fs.lstatSync(runtimeRoot).isSymbolicLink() ||
      normalizePath(fs.realpathSync(runtimeRoot)) !== normalizePath(runtimeRoot)) {
    throw new Error('project_runtime_directory_invalid');
  }
  process.chdir(dashboardRoot);
  const next = require(path.join(dashboardRoot, 'node_modules', 'next'));
  const app = next({ dev: false, dir: dashboardRoot });
  await app.prepare();
  const handler = app.getRequestHandler();
  const server = http.createServer((request, response) => handler(request, response));
  server.listen(3100, '127.0.0.1');
  await new Promise((resolve, reject) => {
    server.once('listening', resolve);
    server.once('error', reject);
  });
  atomicJson(identityPath, identity);

  let stopping = false;
  const finish = async () => {
    if (stopping) return;
    stopping = true;
    clearInterval(stopPoll);
    server.close(async (error) => {
      if (error) {
        console.error('Dashboard graceful close failed:', error.name);
        process.exitCode = 1;
        return;
      }
      try {
        await app.close();
      } catch (closeError) {
        console.error('Dashboard application close failed:', closeError.name);
        process.exitCode = 1;
      }
      try { fs.unlinkSync(identityPath); } catch (unlinkError) {
        if (unlinkError.code !== 'ENOENT') process.exitCode = 1;
      }
      try { fs.unlinkSync(stopPath); } catch (unlinkError) {
        if (unlinkError.code !== 'ENOENT') process.exitCode = 1;
      }
    });
    server.closeIdleConnections?.();
  };

  const stopPoll = setInterval(() => {
    try {
      if (fs.statSync(stopPath).size > 4096) return;
      const request = JSON.parse(fs.readFileSync(stopPath, 'utf8'));
      if (request.pid === identity.pid && request.service === identity.service &&
          request.checkout_root === identity.checkout_root && request.instance_id === identity.instance_id) {
        void finish();
      }
    } catch (error) {
      if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) {
        console.error('Dashboard stop request read failed:', error.name);
      }
    }
  }, 250);
  stopPoll.unref();
  process.on('SIGINT', finish);
  process.on('SIGTERM', finish);
  console.log('Dashboard listening on http://127.0.0.1:3100');
}

main().catch((error) => {
  console.error('Dashboard startup failed:', error.name);
  try { fs.unlinkSync(identityPath); } catch (_) { }
  process.exitCode = 1;
});
