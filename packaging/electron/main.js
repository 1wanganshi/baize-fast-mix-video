const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');
const net = require('net');

const APP_NAME = '白泽混剪';
const DEFAULT_PORT = 8501;
const MAX_PORT_TRIES = 40;
const STARTUP_TIMEOUT = 120_000;

let mainWindow = null;
let backendProcess = null;
let backendLogs = [];

function isPackaged() {
  return app.isPackaged;
}

function getProjectRoot() {
  if (isPackaged()) {
    return path.join(process.resourcesPath, 'backend');
  }
  return path.resolve(__dirname, '..', '..', '..');
}

function getPythonExe(root) {
  const venvPython = path.join(root, '.venv', 'Scripts', 'python.exe');
  const embeddedPython = path.join(root, 'python', 'python311', 'python.exe');

  if (!isPackaged()) {
    if (fs.existsSync(venvPython)) return venvPython;
    return 'uv';
  }

  if (fs.existsSync(venvPython)) return venvPython;
  if (fs.existsSync(embeddedPython)) return embeddedPython;
  throw new Error(`Python runtime not found under ${root}`);
}

function findFreePort(startPort) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(startPort, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
    server.on('error', () => {
      if (startPort - DEFAULT_PORT < MAX_PORT_TRIES) {
        resolve(findFreePort(startPort + 1));
      } else {
        reject(new Error('No free port available'));
      }
    });
  });
}

function waitForReady(url, timeout) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeout;
    function poll() {
      if (Date.now() > deadline) return reject(new Error(`Timed out waiting for ${url}`));
      const req = http.get(url, res => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) {
          resolve();
        } else {
          setTimeout(poll, 500);
        }
      });
      req.setTimeout(2_000, () => {
        req.destroy();
        setTimeout(poll, 500);
      });
      req.on('error', () => setTimeout(poll, 500));
    }
    poll();
  });
}

async function startBackend() {
  const root = getProjectRoot();
  const port = await findFreePort(DEFAULT_PORT);
  const url = `http://127.0.0.1:${port}`;
  const pythonExe = getPythonExe(root);
  const appEntry = path.join(root, 'webui', 'Main.py');

  const env = { ...process.env, PYTHONPATH: root };
  const ffmpegBin = path.join(root, 'tools', 'ffmpeg', 'bin');
  env.PATH = [path.dirname(pythonExe), path.join(path.dirname(pythonExe), 'Scripts'), ffmpegBin, process.env.PATH || ''].join(path.delimiter);

  const streamlitArgs = [
    'streamlit', 'run', appEntry,
    '--server.address', '127.0.0.1',
    '--server.port', String(port),
    '--server.headless', 'true',
    '--server.fileWatcherType', 'none',
    '--server.runOnSave', 'false',
    '--browser.serverAddress', '127.0.0.1',
    '--browser.gatherUsageStats', 'false',
    '--client.toolbarMode', 'minimal',
    '--client.showErrorDetails', 'false',
    '--server.enableCORS', 'true',
  ];
  const cmd = pythonExe === 'uv'
    ? ['run', ...streamlitArgs]
    : ['-m', ...streamlitArgs];

  backendProcess = spawn(pythonExe, cmd, { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  const appendLog = d => {
    const text = String(d).trim();
    if (!text) return;
    backendLogs.push(text);
    if (backendLogs.length > 80) backendLogs = backendLogs.slice(-80);
  };
  backendProcess.stdout.on('data', d => { appendLog(d); console.log(`[backend] ${d}`); });
  backendProcess.stderr.on('data', d => { appendLog(d); console.error(`[backend] ${d}`); });
  backendProcess.on('exit', code => {
    appendLog(`Backend exited ${code}`);
    backendProcess = null;
    console.log(`Backend exited ${code}`);
  });

  await waitForReady(url, STARTUP_TIMEOUT);
  return url;
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

function encodeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function statusPage(title, detail, isError = false) {
  const logText = backendLogs.slice(-35).join('\n');
  return `data:text/html;charset=utf-8,${encodeURIComponent(`<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${APP_NAME}</title>
  <style>
    :root { color-scheme: light dark; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: "Segoe UI", Arial, sans-serif;
      background: #101418;
      color: #eef2f5;
    }
    main {
      width: min(680px, calc(100vw - 48px));
      padding: 36px;
      border: 1px solid #27313a;
      border-radius: 8px;
      background: #151b21;
      box-shadow: 0 22px 70px rgba(0,0,0,.35);
    }
    h1 { margin: 0 0 10px; font-size: 28px; letter-spacing: 0; }
    p { margin: 0; color: #aeb8c2; line-height: 1.6; }
    .bar {
      width: 100%;
      height: 4px;
      margin: 26px 0 18px;
      overflow: hidden;
      border-radius: 999px;
      background: #27313a;
    }
    .bar span {
      display: block;
      width: 42%;
      height: 100%;
      border-radius: inherit;
      background: ${isError ? '#ff6464' : '#37c871'};
      animation: load 1.25s ease-in-out infinite;
    }
    pre {
      margin: 22px 0 0;
      max-height: 260px;
      overflow: auto;
      white-space: pre-wrap;
      color: #c8d1da;
      background: #0b0f13;
      border: 1px solid #27313a;
      border-radius: 6px;
      padding: 14px;
      font-size: 12px;
      line-height: 1.45;
    }
    @keyframes load {
      0% { transform: translateX(-120%); }
      100% { transform: translateX(240%); }
    }
  </style>
</head>
<body>
  <main>
    <h1>${encodeHtml(title)}</h1>
    <p>${encodeHtml(detail)}</p>
    <div class="bar"><span></span></div>
    ${logText ? `<pre>${encodeHtml(logText)}</pre>` : ''}
  </main>
</body>
</html>`)}`;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: APP_NAME,
    show: false,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  mainWindow.loadURL(statusPage(APP_NAME, '正在启动本地视频生成工具...'));
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; stopBackend(); });
}

app.whenReady().then(async () => {
  createWindow();
  try {
    const url = await startBackend();
    if (mainWindow) {
      await mainWindow.loadURL(url);
    }
  } catch (err) {
    console.error('Failed to start:', err);
    if (mainWindow) {
      mainWindow.loadURL(statusPage(
        'Startup failed',
        `${err.message || err}. 请关闭窗口后重新打开白泽混剪。`,
        true,
      ));
    }
  }
});

app.on('window-all-closed', () => { stopBackend(); app.quit(); });
app.on('activate', () => { if (mainWindow === null) app.quit(); });
