/* 冒烟测试：首屏到底有没有「活过来」
 *
 * 用法：node tools/tests/smoke_first_screen.js      （PORT 可覆盖，默认 8765）
 * 前置：本机服务已在跑（python tools/serve.py --no-browser），端口空闲。
 * 依赖：jsdom（脚本自带托管 Node 工作区的模块搜索路径，不必先设 NODE_PATH）
 *
 * 为什么需要这个脚本：v1.0.9 把 app.js 里一处**不存在的标识符引用**
 * （`.then(objOf)`，真实的函数名是 `segObject`）发了出去。后果是最坏的那种：
 *   · tools/verify_release.py 全绿 —— 它只打接口，接口全都 200；
 *   · 浏览器控制台里只有一个未捕获的 promise 错误；
 *   · 页面上永远停在「正在载入… / 正在载入节目单…」，也就是用户看到的
 *     「连接无响应」，而且**连 /api/programs 都不会被请求**（启动链第一环就断了）。
 * 所以「接口都对」不足以说明页面能用 —— 这个脚本真实执行 app.js，
 * 任何未捕获异常都直接 FAIL。
 *
 * 判据（不是看某一个瞬间的画面）：
 *   1. 没有任何未捕获异常 / 控制台错误
 *   2. 启动链真的走完了：分段占位被替换、标题不再是「正在载入…」
 *   3. 清单接口（/api/programs）确实被请求过 —— 这一条专门拦「链子断在前半段」
 *   4. 列表渲染出至少一行（B 站取不到清单时降级为提示，不算失败）
 *
 * 测哪一位：服务端已有主播就借用第一位（只读，不动注册表）；只有空表时才临时
 * 注册一位，跑完（含失败）都会删掉。
 */
const fs = require('fs');
const path = require('path');
const HOME = process.env.HOME || process.env.USERPROFILE;
const WS = path.join(HOME, '.workbuddy/binaries/node/workspace/node_modules');
if (fs.existsSync(WS)) {
  process.env.NODE_PATH = WS;
  require('module').Module._initPaths();
  module.paths.push(WS);
}
const { JSDOM, VirtualConsole, requestInterceptor } = require('jsdom');

const PORT = process.env.PORT || 8765;
const ORIGIN = 'http://127.0.0.1:' + PORT;
const WWW = process.env.WWW || path.join(__dirname, '..', '..');
const MID = process.env.SMOKE_MID || '490589965';      // 一位有回放的主播（只用于临时注册）
const PLACEHOLDER_PICK = '正在载入…';
const PLACEHOLDER_SEG = '分段数据载入中…';
const IGNORE = [/Not implemented: HTMLMediaElement/, /Not implemented: HTMLCanvasElement/,
  /Not implemented: navigation/, /Could not parse CSS/, /Settings parameter/,
  /Could not load script.*(mpegts|dash)/i];
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml' };

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const T = (s) => String(s || '').replace(/\s+/g, ' ').trim();

const localFiles = requestInterceptor((req) => {
  const p = decodeURIComponent(new URL(req.url).pathname);
  if (p.includes('dash.all.min.js') || p.includes('mpegts')) return undefined;
  const f = path.join(WWW, p.replace(/^\//, '') || 'index.html');
  if (fs.existsSync(f) && fs.statSync(f).isFile()) {
    return new Response(fs.readFileSync(f), { status: 200,
      headers: { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' } });
  }
});

let ok = 0, bad = 0;
/* 页面里未被任何 catch 接住的异常，jsdom 会直接抛到 Node 这一层。不拦住的话
   脚本会「崩掉」而不是给出 FAIL —— 崩掉也算失败，但读不出是哪一条断言，
   而且日志里只剩一段栈。所以兜住它，当成一条错误参与断言。 */
const CRASH = [];
process.on('uncaughtException', (e) => {
  CRASH.push('uncaughtException: ' + ((e && e.message) || e));
});
process.on('unhandledRejection', (e) => {
  CRASH.push('unhandledRejection: ' + ((e && e.message) || e));
});

function check(name, cond, detail) {
  if (cond) { ok++; console.log('  PASS  ' + name); }
  else { bad++; console.log('  FAIL  ' + name + (detail ? '   ' + detail : '')); }
}

/* ---------- 挑一位来测 ---------- */
async function post(p, body) {
  const r = await fetch(ORIGIN + p, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.json();
}
async function get(p) {
  const r = await fetch(ORIGIN + p);
  return r.json();
}

/* 服务端**已经有人**就借用第一位（只读，绝不写注册表）；只有空表（出厂默认）时
   才临时加一位、跑完删掉。按 mid 覆盖式注册再按名字清理是危险写法：
   目标 mid 恰好是用户已有的主播时，会先改名、再被清理逻辑连人一起删掉。 */
async function pickStation() {
  const list = (await get('/api/stations')).stations || [];
  if (list.length) return { id: String(list[0].id), created: false };
  await post('/api/stations/save', { mid: MID, name: '冒烟·首屏' });
  const l2 = (await get('/api/stations')).stations || [];
  const me = l2.filter((s) => String(s.mid) === String(MID))[0];
  return { id: me ? String(me.id) : '', created: true };
}
async function cleanup(created, id) {
  if (!created || !id) return;
  try { await post('/api/stations/delete', { id: id }); } catch (e) { /* 收尾失败不影响结论 */ }
}

function open(log, stationId) {
  const vc = new VirtualConsole();
  vc.on('jsdomError', (e) => {
    const m = String((e && e.message) || e);
    if (!IGNORE.some((re) => re.test(m))) log.errors.push('jsdomError: ' + m);
  });
  vc.on('error', (...a) => log.errors.push('console.error: ' + a.join(' ')));
  vc.on('warn', (...a) => log.warns.push(String(a.join(' ')).slice(0, 120)));
  // 页面自己的 console.log 会直接落到本进程的 stdout（jsdom 的默认行为），
  // 把结果表格冲得很难读 —— 收走，不进断言。
  vc.on('log', () => {});
  vc.on('info', () => {});

  return JSDOM.fromURL(ORIGIN + '/', {
    runScripts: 'dangerously',
    resources: { interceptors: [localFiles] },
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(w) {
      // 新开页面会先停在「选择频道」页；这里跳过它（真实用户点过卡就会有这个标记）
      try {
        w.sessionStorage.setItem('xl_picked', '1');
        w.localStorage.setItem('xl_stations', JSON.stringify([stationId]));
      } catch (e) { log.errors.push('无法写 sessionStorage：' + e.message); }

      const P = w.HTMLMediaElement.prototype;
      Object.defineProperty(P, 'readyState', { get: () => 4, configurable: true });
      Object.defineProperty(P, 'duration', { get: () => 1e9, configurable: true });
      Object.defineProperty(P, 'paused', { get: () => false, configurable: true });
      Object.defineProperty(P, 'currentTime', {
        get: () => 0, set() {}, configurable: true });
      Object.defineProperty(P, 'src', { get: () => '', set() {}, configurable: true });
      P.play = () => Promise.resolve();
      P.pause = () => {};

      const real = (typeof fetch === 'function') ? fetch : null;
      w.fetch = (u, o) => {
        const s = String(u);
        const abs = s.startsWith('/') ? ORIGIN + s : s;
        if (s.includes('/api/programs')) log.programs.push(s);
        if (s.includes('/api/ping'))
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: 1 }) });
        if (s.includes('/api/dash?'))
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ error: 'FAKE-DASH-OFF' }) });
        if (s.includes('/api/playurl?'))
          return Promise.resolve({ ok: true, json: () => Promise.resolve({
            media: ORIGIN + '/fake.mp4', quality: 64, accept: [{ qn: 64, desc: '720P' }] }) });
        if (s.includes('/api/stream'))
          return Promise.resolve({ ok: false, status: 599, json: () => Promise.resolve({}) });
        return real ? real(abs, o) : Promise.reject(new Error('无可用 fetch'));
      };
    }
  });
}

(async () => {
  console.log('=== 首屏启动链冒烟（%s）===' % ORIGIN);
  let st = { id: '', created: false };
  try {
    st = await pickStation();
    if (!st.id) { console.log('  拿不到可测的主播，无法继续'); process.exitCode = 1; return; }
    console.log('  测的主播 id = %s（%s）', st.id,
      st.created ? '临时注册，跑完会删掉' : '服务端已有的，只读不写');
    const id = st.id;

    const log = { errors: [], warns: [], programs: [] };
    const dom = await open(log, id);
    const w = dom.window, doc = w.document;

    // 等到「标题不再是占位」或超时
    let waited = 0;
    while (waited < 60000 && T(doc.querySelector('#np-title') && doc.querySelector('#np-title').textContent) === PLACEHOLDER_PICK) {
      await sleep(250); waited += 250;
    }
    await sleep(1500);        // 给列表渲染留一点时间

    const segCov = T(doc.querySelector('#seg-cov') && doc.querySelector('#seg-cov').textContent);
    const npTitle = T(doc.querySelector('#np-title') && doc.querySelector('#np-title').textContent);
    const rows = doc.querySelectorAll('#rows [data-play]').length;
    const booted = !!w.__STATE;

    console.log('  等待 %dms 后：segCov=%j npTitle=%j rows=%d programs 请求 %d 次',
      waited, segCov.slice(0, 40), npTitle.slice(0, 40), rows, log.programs.length);

    console.log('\n--- 1. 没有未捕获异常 ---');
    const allErr = log.errors.concat(CRASH);
    check('页面没有未捕获异常／控制台错误', allErr.length === 0,
      allErr.slice(0, 3).join(' ‖ '));

    console.log('\n--- 2. 启动链真的走完了 ---');
    check('分段占位已被替换（loadStationSegments 没崩）', segCov !== '' && segCov !== PLACEHOLDER_SEG, segCov.slice(0, 60));
    check('标题不再是「正在载入…」（boot() 跑到了）', npTitle !== '' && npTitle !== PLACEHOLDER_PICK, npTitle.slice(0, 60));
    check('window.__STATE 已建立', booted);

    console.log('\n--- 3. 清单接口被请求过（断在半路会在这里暴露）---');
    check('/api/programs 至少被请求 1 次', log.programs.length >= 1, String(log.programs.length));

    console.log('\n--- 4. 列表渲染 ---');
    if (rows > 0) {
      check('节目单渲染出至少一行', true, rows + ' 行');
    } else {
      const empty = doc.querySelector('#station-empty');
      const why = empty ? T(empty.textContent).slice(0, 60) : '(无提示)';
      const all = (w.__STATE && (w.__STATE.all || []).length) || 0;
      const body = T(doc.querySelector('#rows') && doc.querySelector('#rows').textContent).slice(0, 80);
      console.log('  SKIP  节目单 0 行 —— 这次没取到清单；本条不作结论（启动链看上面几条）');
      console.log('        内存里有 %d 条清单；表格里写着：%j；空态提示：%j', all, body, why);
    }

    w.close();
  } catch (e) {
    bad++;
    console.log('  FAIL  脚本自身异常：' + (e && e.stack || e));
  } finally {
    await cleanup(st.created, st.id);
  }

  console.log('\n---------------- %d 通过 / %d 失败 ----------------', ok, bad);
  process.exitCode = bad ? 1 : 0;
})();
