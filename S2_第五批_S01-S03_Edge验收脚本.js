/* ===== 康迹 HealthTrack · S2 第五批 S-01~S-03 人工验收（一键块 · 无模板串版）=====
   位置：浏览器 F12 -> Console（页面须停在 http://127.0.0.1:5000/api/v1/health）
   账号：acctest01（本端）、acctest02（对端，用于验证隔离）
   密码：Kangji2026（8~64 位、含字母与数字、无空格、不等于用户名）
   说明：本版【不使用 ES6 模板字符串】，全部改为字符串拼接，
        避免反引号在"查看 / 复制"环节被吞掉导致 Uncaught SyntaxError: missing ) after argument list。
   覆盖：S-01 首页概览 / S-02 趋势数据 / S-03 统计摘要
        —— 全字段、8 指标、半开边界、缺失不补零、软删、跨用户隔离、参数校验。
   前置：后端已启动（cd backend && .venv/Scripts/python.exe wsgi.py），5000 端口存活。
   收尾：脚本会自行清理本次测试数据（仅 acctest01 / acctest02 范围）。
   ========================================================================= */
(async () => {
  const BASE = location.origin + '/api/v1';
  const PWD = 'Kangji2026';
  const UA = 'acctest01';
  const UB = 'acctest02';

  const R = [];
  const ok = function (name, cond, extra) {
    const tail = (extra === undefined || extra === null || extra === '') ? '' : '   -> ' + extra;
    R.push((cond ? '[OK]   ' : '[FAIL] ') + name + tail);
  };
  const eq = function (a, b) { return JSON.stringify(a) === JSON.stringify(b); };
  const deepEq = function (a, b) {
    if (a === b) { return true; }
    if (a === null || b === null) { return a === b; }
    if (typeof a !== typeof b) { return false; }
    if (Array.isArray(a) !== Array.isArray(b)) { return false; }
    if (Array.isArray(a)) {
      if (a.length !== b.length) { return false; }
      for (let i = 0; i < a.length; i++) { if (!deepEq(a[i], b[i])) { return false; } }
      return true;
    }
    if (typeof a === 'object') {
      const ka = Object.keys(a).sort();
      const kb = Object.keys(b).sort();
      if (ka.length !== kb.length) { return false; }
      for (let i = 0; i < ka.length; i++) {
        if (ka[i] !== kb[i]) { return false; }
        if (!deepEq(a[ka[i]], b[ka[i]])) { return false; }
      }
      return true;
    }
    return false;
  };
  const okEq = function (name, actual, expected) {
    const same = deepEq(actual, expected);
    ok(name, same, same ? '' : ('期望 ' + JSON.stringify(expected) + ' / 实际 ' + JSON.stringify(actual)));
  };
  const show = function (v) {
    try { return JSON.stringify(v); } catch (e) { return String(v); }
  };

  const D = function (r) { return (r && r.b && r.b.data) || {}; };
  const CODE = function (r) { return (r && r.b && r.b.code) || ''; };
  const ITEMS = function (r) { return D(r).items || []; };
  const HEX32 = /^[0-9a-f]{32}$/;

  const pad = function (n) { return String(n).padStart(2, '0'); };
  const fmt = function (d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' +
           pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  };
  const rawDate = function (d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  };
  const dayOff = function (n) {
    const d = new Date();
    d.setDate(d.getDate() + n);
    return d;
  };
  const dayStr = function (n) { return rawDate(dayOff(n)); };
  const stamp = function (n, h, m, s) {
    const d = dayOff(n);
    d.setHours(h, m, s, 0);
    return fmt(d);
  };
  const back = function (n, h, m, s, hours) {
    const d = dayOff(n);
    d.setHours(h, m, s, 0);
    return fmt(new Date(d.getTime() - hours * 3600 * 1000));
  };
  const nowS = function () { return fmt(new Date()); };

  const call = async function (m, p, body, tok) {
    const h = {};
    if (body !== undefined) { h['Content-Type'] = 'application/json'; }
    if (tok) { h['Authorization'] = 'Bearer ' + tok; }
    const res = await fetch(BASE + p, {
      method: m,
      headers: h,
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    let j = null;
    try { j = await res.json(); } catch (e) { j = null; }
    return { s: res.status, b: j };
  };

  const boot = async function (u) {
    await call('POST', '/auth/register', {
      username: u, password: PWD, agreement_version: 'v1.0', agreement_accepted: true
    });
    const r = await call('POST', '/auth/login', { username: u, password: PWD });
    if (r.s !== 200) {
      throw new Error('账号 ' + u + ' 登录失败 HTTP ' + r.s +
                      '（若曾改过密码，请先在数据库/管理通道重置，或换用其它 acctest0x 账号）');
    }
    return D(r).tokens.access_token;
  };

  const purge = async function (tok) {
    let n = 0;
    for (let guard = 0; guard < 50; guard++) {
      const r = await call('GET', '/records?limit=100', undefined, tok);
      const items = ITEMS(r);
      if (!items.length) { break; }
      for (let i = 0; i < items.length; i++) {
        await call('DELETE', '/records/' + items[i].id, undefined, tok);
        n++;
      }
      if (!D(r).has_more) { break; }
    }
    const g = await call('GET', '/goals?include_paused=true', undefined, tok);
    const goals = ITEMS(g);
    for (let i = 0; i < goals.length; i++) {
      await call('DELETE', '/goals/' + goals[i].id, undefined, tok);
      n++;
    }
    return n;
  };

  const go = async function (title, fn) {
    console.log('\n----- ' + title + ' -----');
    try { await fn(); }
    catch (e) { R.push('[FAIL] ' + title + ' 执行异常：' + (e && e.message)); }
  };

  let tA = null, tB = null;
  let newRecs = [], newGoals = [];
  let waterGoalId = null, weightGoalId = null;

  const addRec = async function (tok, payload) {
    const r = await call('POST', '/records', payload, tok);
    if (r.s !== 201) {
      throw new Error('R-01 写入失败 HTTP ' + r.s + ' ' + show(r.b) + ' payload=' + show(payload));
    }
    const rec = D(r).record;
    newRecs.push(rec.id);
    return rec.id;
  };
  const addGoal = async function (tok, payload) {
    const r = await call('POST', '/goals', payload, tok);
    if (r.s !== 201) {
      throw new Error('G-02 建目标失败 HTTP ' + r.s + ' ' + show(r.b) + ' payload=' + show(payload));
    }
    const g = D(r).goal;
    newGoals.push({ tok: tok, id: g.id });
    return g.id;
  };
  const trend = function (tok, q) { return call('GET', '/stats/trend' + (q || ''), undefined, tok); };
  const summary = function (tok, q) { return call('GET', '/stats/summary' + (q || ''), undefined, tok); };
  const overview = function (tok) { return call('GET', '/home/overview', undefined, tok); };
  const at = function (list, d) {
    for (let i = 0; i < (list || []).length; i++) { if (list[i].date === d) { return list[i]; } }
    return null;
  };
  const METRIC_TYPES = ['weight', 'bp', 'heart', 'glucose', 'sleep', 'water', 'sport', 'mood'];

  try {
    console.log('准备两个测试账号 acctest01 / acctest02 ...');
    tA = await boot(UA);
    tB = await boot(UB);
    console.log('两个账号就绪，开始清理历史测试数据 ...');
    const p1 = await purge(tA);
    const p2 = await purge(tB);
    console.log('预清理完成：本端 ' + p1 + ' 条、对端 ' + p2 + ' 条');

    /* ============================== 1. S-01 空态 ============================== */
    await go('S-01 空态（无数据仍 200，空态由客户端渲染）', async function () {
      const r = await overview(tA);
      ok('S-01 空态 HTTP 200', r.s === 200, 'HTTP ' + r.s);
      okEq('S-01 空态 code=OK', CODE(r), 'OK');
      const d = D(r);
      okEq('S-01 顶层字段恰为 5 个', Object.keys(d).sort(),
           ['date', 'goals', 'recent_records', 'reminder_fallback', 'today']);
      okEq('S-01 date = 今天', d.date, dayStr(0));
      okEq('S-01 today = {0, []}', d.today, { record_count: 0, metric_types_recorded: [] });
      okEq('S-01 goals = []（不是 404）', d.goals, []);
      okEq('S-01 recent_records = []', d.recent_records, []);
      okEq('S-01 reminder_fallback 固定占位语义', d.reminder_fallback,
           { source: 'local', note: 'N/A（提醒兜底计数由客户端本地计算，服务端不提供）' });
    });

    /* ============================== 2. 鉴权与身份守卫 ============================== */
    await go('鉴权 / 身份守卫 / envelope（三接口）', async function () {
      const probes = [
        { p: '/home/overview', q: '' },
        { p: '/stats/trend', q: '?metric_type=water' },
        { p: '/stats/summary', q: '?metric_type=water' }
      ];
      let envAll = true, envDetail = '';
      for (let i = 0; i < probes.length; i++) {
        const r = await call('GET', probes[i].p + probes[i].q);
        const b = r.b || {};
        const good = (r.s === 401) && (b.code === 'UNAUTHENTICATED') && (b.data === null) &&
                     eq(Object.keys(b).sort(), ['code', 'data', 'message', 'request_id']) &&
                     HEX32.test(String(b.request_id));
        if (!good) { envAll = false; envDetail = probes[i].p + ' HTTP ' + r.s + ' ' + show(b); }
      }
      ok('三接口 无 Token -> 401 UNAUTHENTICATED + 四字段 envelope + 32 位 request_id',
         envAll, envDetail);

      let g1 = true, g1d = '';
      for (let i = 0; i < probes.length; i++) {
        const sep = probes[i].q === '' ? '?' : '&';
        const r = await call('GET', probes[i].p + probes[i].q + sep + 'user_id=1');
        if (!(r.s === 400 && CODE(r) === 'INVALID_PARAM')) {
          g1 = false; g1d = probes[i].p + ' HTTP ' + r.s + ' ' + CODE(r);
        }
      }
      ok('三接口 query 携带 user_id -> 400 INVALID_PARAM（全局守卫）', g1, g1d);

      // ★ 本项唯一修改点（验收脚本写法，非后端）：fetch 规范禁止 GET/HEAD 携带 body，
      //   原写法 call('GET', path, {user_id:1}) 会让浏览器直接抛
      //   TypeError: Request with GET/HEAD method cannot have body（验收块整体中断）。
      //   改法：以 POST 把**同一 JSON 体**投递到**同一条路径**——全局守卫是
      //   before_request（检查 request.args + request.get_json），先于方法判定执行，
      //   守卫代码路径与 GET 时完全一致；下方对照项（同路径 POST 不带 user_id
      //   -> 405 Method Not Allowed）证明 400 来自守卫而非 405，断言强度不变。
      let g2 = true, g2d = '';
      for (let i = 0; i < probes.length; i++) {
        const r = await call('POST', probes[i].p + probes[i].q, { user_id: 1 });
        const ctl = await call('POST', probes[i].p + probes[i].q, { note: 'x' });
        if (!(r.s === 400 && CODE(r) === 'INVALID_PARAM')) {
          g2 = false; g2d = probes[i].p + ' HTTP ' + r.s + ' ' + CODE(r);
        }
        if (ctl.s !== 405) {
          g2 = false; g2d = '对照（同路径 POST 无 user_id）' + probes[i].p + ' HTTP ' + ctl.s;
        }
      }
      ok('三接口 JSON 体携带 user_id -> 400 INVALID_PARAM（全局守卫；GET 不可带体，以 POST 投递同路径）',
         g2, g2d);

      const noTok = await call('GET', '/stats/trend?metric_type=water&window=15');
      ok('无 Token 时鉴权优先（非法参数不提前暴露 400）', noTok.s === 401,
         'HTTP ' + noTok.s);
    });

    /* ============================== 3. 造数（仅本端 acctest01） ============================== */
    await go('造数（R-01 真实写入 · 覆盖 8 指标 + 边界）', async function () {
      // weight：d-3 当日两条 -> 取最后一次 71.5；d-2 71.00 -> 整数归一
      await addRec(tA, { metric_type: 'weight', value_1: 72.0, recorded_at: stamp(-6, 9, 0, 0) });
      await addRec(tA, { metric_type: 'weight', value_1: 71.5, recorded_at: stamp(-4, 9, 0, 0) });
      await addRec(tA, { metric_type: 'weight', value_1: 70.50, recorded_at: stamp(-3, 8, 0, 0) });
      await addRec(tA, { metric_type: 'weight', value_1: 71.50, recorded_at: stamp(-3, 20, 0, 0) });
      await addRec(tA, { metric_type: 'weight', value_1: 71.00, recorded_at: stamp(-2, 9, 0, 0) });
      // water：start 当天 00:00:00（含）/ start-1s（不含）/ 次日 00:00:00（含）/ end 当天 23:59:59（含）
      await addRec(tA, { metric_type: 'water', value_1: 2000, recorded_at: stamp(-7, 23, 59, 59) });
      await addRec(tA, { metric_type: 'water', value_1: 1000, recorded_at: stamp(-6, 0, 0, 0) });
      await addRec(tA, { metric_type: 'water', value_1: 300, recorded_at: stamp(-5, 0, 0, 0) });
      await addRec(tA, { metric_type: 'water', value_1: 1500, recorded_at: stamp(-2, 9, 0, 0) });
      await addRec(tA, { metric_type: 'water', value_1: 900, recorded_at: stamp(-2, 21, 0, 0) });
      await addRec(tA, { metric_type: 'water', value_1: 300, recorded_at: stamp(-1, 9, 0, 0) });
      await addRec(tA, { metric_type: 'water', value_1: 500, recorded_at: stamp(-1, 23, 59, 59) });
      // bp：两日各一条
      await addRec(tA, { metric_type: 'bp', value_1: 120, value_2: 80, recorded_at: stamp(-5, 8, 0, 0) });
      await addRec(tA, { metric_type: 'bp', value_1: 130, value_2: 90, recorded_at: stamp(-2, 8, 0, 0) });
      // heart：一条 resting（供 resting_average）
      await addRec(tA, { metric_type: 'heart', value_1: 60, attr_1: 'resting', recorded_at: stamp(-2, 8, 0, 0) });
      await addRec(tA, { metric_type: 'heart', value_1: 80, recorded_at: stamp(-2, 20, 0, 0) });
      // glucose：fasting ×2 + after_meal_2h ×1
      await addRec(tA, { metric_type: 'glucose', value_1: 5.5, attr_1: 'fasting', recorded_at: stamp(-2, 7, 0, 0) });
      await addRec(tA, { metric_type: 'glucose', value_1: 6.5, attr_1: 'fasting', recorded_at: stamp(-1, 7, 0, 0) });
      await addRec(tA, { metric_type: 'glucose', value_1: 8.0, attr_1: 'after_meal_2h', recorded_at: stamp(-1, 20, 0, 0) });
      // sleep：跨天（time_start 为前一晚），时长 8.5h / 6.5h
      await addRec(tA, { metric_type: 'sleep', value_1: 5, time_start: back(-2, 7, 0, 0, 8.5), recorded_at: stamp(-2, 7, 0, 0) });
      await addRec(tA, { metric_type: 'sleep', value_1: 4, time_start: back(-1, 7, 0, 0, 6.5), recorded_at: stamp(-1, 7, 0, 0) });
      // sport：同日两条 30 + 45
      await addRec(tA, { metric_type: 'sport', value_1: 30, attr_1: 'running', recorded_at: stamp(-1, 9, 0, 0) });
      await addRec(tA, { metric_type: 'sport', value_1: 45, attr_1: 'walking', recorded_at: stamp(-1, 10, 0, 0) });
      // mood：带 tags
      await addRec(tA, { metric_type: 'mood', value_1: 4, tags: ['relaxed'], recorded_at: stamp(-2, 9, 0, 0) });
      await addRec(tA, { metric_type: 'mood', value_1: 2, tags: ['tired', 'relaxed'], recorded_at: stamp(-1, 9, 0, 0) });
      // 目标 25 的逐项依据（每条记录都被下方断言唯一消费，无冗余写入）：
      //   weight  5 = d-6 72.0 / d-4 71.5 / d-3 两条(70.50+71.50 测"同日取最后一次"->71.5) / d-2 71.00(整数归一)
      //   water   7 = d-7 23:59:59(默认 7 天窗口外，供 end=过去日 时重新纳入) / d-6 00:00:00(窗口起点含) /
      //               d-5 00:00:00 / d-2 两条(1500+900=2400 测同日累计) / d-1 两条(300+500=800，末点 23:59:59 含)
      //   bp      2 = d-5 120/80 + d-2 130/90        -> 均价 125/85、max/min、measure_count=2
      //   heart   2 = d-2 60(resting) + d-2 80       -> average 70、resting_average 60
      //   glucose 3 = fasting 5.5 / fasting 6.5 / after_meal_2h 8.0 -> 日均 5.5、7.25；fasting 6、after_meal 8
      //   sleep   2 = d-2 8.5h(质量 5) + d-1 6.5h(质量 4) -> 均 7.5 / 4.5、longest/shortest、达标率 50%
      //   sport   2 = d-1 30 + 45（同日两条）          -> minutes 75、count 2、weekly 恰 1 桶
      //   mood    2 = d-2 relaxed(4) + d-1 tired+relaxed(2) -> 均分 3、tag_distribution relaxed 2 / tired 1
      //   合计 5+7+2+2+3+2+2+2 = 25（与 scripts/s2_batch5_http_smoke.py 造数 25 条同源一致）
      ok('造数：本端写入 ' + newRecs.length + ' 条记录（目标 25 条 · 逐指标 5+7+2+2+3+2+2+2）',
         newRecs.length === 25, '实际 ' + newRecs.length);

      waterGoalId = await addGoal(tA, { goal_type: 'water', target_value: 2000 });
      weightGoalId = await addGoal(tA, { goal_type: 'weight', target_value: 68.0, start_weight_kg: 72.5 });
      await addGoal(tA, { goal_type: 'sleep', target_value: 8 });
      ok('造数：本端 3 个自设目标（water / weight / sleep）', newGoals.length === 3,
         '实际 ' + newGoals.length);
    });

    /* ============================== 4. S-02 趋势数据 ============================== */
    await go('S-02 骨架 / 窗口 / 半开边界 / 缺失不补零', async function () {
      const r = await trend(tA, '?metric_type=water');
      const d = D(r);
      ok('S-02 HTTP 200', r.s === 200, 'HTTP ' + r.s);
      okEq('S-02 骨架字段', Object.keys(d).sort(),
           ['chart', 'insufficient_data', 'metric_type', 'points', 'target_line', 'unit', 'window']);
      okEq('S-02 unit = ml', d.unit, 'ml');
      okEq('S-02 chart = bar', d.chart, 'bar');
      okEq('S-02 window 默认 7 天', d.window,
           { days: 7, start: dayStr(-6), end: dayStr(0) });
      okEq('S-02 water points（start 00:00:00 含 / start-1s 不含 / 次日 00:00:00 含 / end 23:59:59 含 / 同日累计）',
           d.points, [
             { date: dayStr(-6), total_ml: 1000 },
             { date: dayStr(-5), total_ml: 300 },
             { date: dayStr(-2), total_ml: 2400 },
             { date: dayStr(-1), total_ml: 800 }
           ]);
      ok('S-02 insufficient_data = false（4 个点）', d.insufficient_data === false);
      okEq('S-02 target_line（water 自设目标 2000）', d.target_line,
           { value: 2000, unit: 'ml', source: 'health_goal', goal_id: waterGoalId });

      const w30 = D(await trend(tA, '?metric_type=water&window=30')).window;
      okEq('S-02 window=30 -> start = end-29', w30, { days: 30, start: dayStr(-29), end: dayStr(0) });
      const w90 = D(await trend(tA, '?metric_type=water&window=90')).window;
      okEq('S-02 window=90 -> start = end-89', w90, { days: 90, start: dayStr(-89), end: dayStr(0) });

      const hist = D(await trend(tA, '?metric_type=water&end=' + dayStr(-3))).points;
      okEq('S-02 end=过去日 -> 窗口随 end 收窄（start=d-9，d-7 23:59:59 重新纳入）',
           hist, [
             { date: dayStr(-7), total_ml: 2000 },
             { date: dayStr(-6), total_ml: 1000 },
             { date: dayStr(-5), total_ml: 300 }
           ]);

      const fut = D(await trend(tA, '?metric_type=water&end=' + dayStr(100)));
      okEq('S-02 end=未来日（T-4 允许，仅格式校验）-> 空数据 200, 不报错', fut.points, []);
      ok('S-02 未来窗口 insufficient_data = true', fut.insufficient_data === true);
    });

    await go('S-02 逐指标日聚合（weight / bp / heart / glucose / sleep / sport / mood）', async function () {
      const wt = D(await trend(tA, '?metric_type=weight'));
      okEq('S-02 weight 当日取最后一次 + 逐日均值以外口径',
           wt.points, [
             { date: dayStr(-6), value: 72 },
             { date: dayStr(-4), value: 71.5 },
             { date: dayStr(-3), value: 71.5 },
             { date: dayStr(-2), value: 71 }
           ]);
      const p2 = at(wt.points, dayStr(-2));
      ok('S-02 weight 整数归一为 int（70.00 -> 70）',
         p2 !== null && Number.isInteger(p2.value), p2 ? show(p2.value) : 'null');
      okEq('S-02 weight target_line（自设目标 68 kg）', wt.target_line,
           { value: 68, unit: 'kg', source: 'health_goal', goal_id: weightGoalId });

      const bp = D(await trend(tA, '?metric_type=bp'));
      okEq('S-02 bp 当日双值算术平均', bp.points,
           [{ date: dayStr(-5), systolic: 120, diastolic: 80 },
            { date: dayStr(-2), systolic: 130, diastolic: 90 }]);
      ok('S-02 bp insufficient_data = false（2 个点）', bp.insufficient_data === false);
      const bp1 = D(await trend(tA, '?metric_type=bp&end=' + dayStr(-3)));
      okEq('S-02 bp 单点窗口 points', bp1.points,
           [{ date: dayStr(-5), systolic: 120, diastolic: 80 }]);
      ok('S-02 bp 单点 insufficient_data = true', bp1.insufficient_data === true);

      const hr = D(await trend(tA, '?metric_type=heart'));
      okEq('S-02 heart 当日 value_1 平均', hr.points, [{ date: dayStr(-2), value: 70 }]);

      const gl = D(await trend(tA, '?metric_type=glucose'));
      ok('S-02 glucose 未指定 group_by 时不含 groups', !('groups' in gl));
      okEq('S-02 glucose 当日均分', gl.points,
           [{ date: dayStr(-2), value: 5.5 }, { date: dayStr(-1), value: 7.25 }]);
      const gg = D(await trend(tA, '?metric_type=glucose&group_by=timing'));
      okEq('S-02 glucose groups（按 timing 枚举固定序）', gg.groups,
           [{ timing: 'fasting', value: 6 }, { timing: 'after_meal_2h', value: 8 }]);

      const sl = D(await trend(tA, '?metric_type=sleep'));
      okEq('S-02 sleep unit = score', sl.unit, 'score');
      okEq('S-02 sleep 时长累计（1 位小数）+ 质量均分', sl.points,
           [{ date: dayStr(-2), duration_hours: 8.5, quality: 5 },
            { date: dayStr(-1), duration_hours: 6.5, quality: 4 }]);

      const sp = D(await trend(tA, '?metric_type=sport'));
      okEq('S-02 sport 当日分钟累计 + 条数', sp.points,
           [{ date: dayStr(-1), minutes: 75, count: 2 }]);
      const wk = sp.weekly || [];
      ok('S-02 sport weekly 仅 1 个周桶', wk.length === 1, '实际 ' + wk.length);
      if (wk.length === 1) {
        okEq('S-02 sport weekly 元素形态', Object.keys(wk[0]).sort(),
             ['count', 'minutes', 'week_start']);
        ok('S-02 sport weekly 数值 75 / 2', wk[0].minutes === 75 && wk[0].count === 2,
           show(wk[0]));
        const wd = new Date(wk[0].week_start + 'T00:00:00');
        ok('S-02 sport week_start 为周一', wd.getDay() === 1, wk[0].week_start);
      }

      const md = D(await trend(tA, '?metric_type=mood'));
      okEq('S-02 mood 当日均分', md.points,
           [{ date: dayStr(-2), value: 4 }, { date: dayStr(-1), value: 2 }]);
      okEq('S-02 mood tag_distribution（按 mood_tags 固定序，仅 count>=1）', md.tag_distribution,
           [{ tag: 'tired', count: 1 }, { tag: 'relaxed', count: 2 }]);
    });

    await go('S-02 chart 逐指标 / target_line 仅 weight+water', async function () {
      const CHART = { weight: 'line', bp: 'line', heart: 'line', glucose: 'line',
                      sleep: 'bar', water: 'bar', sport: 'bar', mood: 'line' };
      let all = true, det = '';
      for (let i = 0; i < METRIC_TYPES.length; i++) {
        const m = METRIC_TYPES[i];
        const d = D(await trend(tA, '?metric_type=' + m));
        if (d.chart !== CHART[m]) { all = false; det = m + ' -> ' + d.chart; }
      }
      ok('S-02 chart 逐指标正确（折线 5 / 柱状 3）', all, det);

      let tl = true, tld = '';
      const others = ['bp', 'heart', 'glucose', 'sleep', 'sport', 'mood'];
      for (let i = 0; i < others.length; i++) {
        const d = D(await trend(tA, '?metric_type=' + others[i]));
        if ('target_line' in d) { tl = false; tld = others[i]; }
      }
      ok('S-02 非 weight/water 指标无 target_line 键', tl, tld);
    });

    await go('S-02 参数校验（400 INVALID_PARAM）', async function () {
      const badMetric = ['', 'blood', 'WATER', 'bp2'];
      let a = true, ad = '';
      let r = await trend(tA, '');
      if (!(r.s === 400 && CODE(r) === 'INVALID_PARAM')) { a = false; ad = '缺 metric_type -> ' + r.s; }
      for (let i = 0; i < badMetric.length; i++) {
        r = await trend(tA, '?metric_type=' + badMetric[i]);
        if (!(r.s === 400 && CODE(r) === 'INVALID_PARAM')) { a = false; ad = badMetric[i] + ' -> ' + r.s; }
      }
      ok('S-02 metric_type 必填且仅 8 类 -> 400', a, ad);

      const badWin = ['0', '1', '14', '31', '91', '-7', 'abc', '7.5'];
      let b = true, bd = '';
      for (let i = 0; i < badWin.length; i++) {
        r = await trend(tA, '?metric_type=water&window=' + badWin[i]);
        if (!(r.s === 400 && CODE(r) === 'INVALID_PARAM')) { b = false; bd = 'window=' + badWin[i] + ' -> ' + r.s; }
      }
      ok('S-02 window 仅 7/30/90 -> 400', b, bd);

      const badEnd = ['2026-9-1', '2026/09/01', 'abc', '2026-13-01'];
      let c = true, cd = '';
      for (let i = 0; i < badEnd.length; i++) {
        r = await trend(tA, '?metric_type=water&end=' + badEnd[i]);
        if (!(r.s === 400 && CODE(r) === 'INVALID_PARAM')) { c = false; cd = 'end=' + badEnd[i] + ' -> ' + r.s; }
      }
      ok('S-02 end 非法格式 -> 400', c, cd);

      const badGb = ['?metric_type=water&group_by=timing', '?metric_type=glucose&group_by=tag',
                     '?metric_type=mood&group_by=timing', '?metric_type=water&group_by=tag',
                     '?metric_type=glucose&group_by=xyz'];
      let e = true, ed = '';
      for (let i = 0; i < badGb.length; i++) {
        r = await trend(tA, badGb[i]);
        if (!(r.s === 400 && CODE(r) === 'INVALID_PARAM')) { e = false; ed = badGb[i] + ' -> ' + r.s; }
      }
      ok('S-02 非法 group_by 组合 -> 400', e, ed);
    });

    /* ============================== 5. S-03 统计摘要 ============================== */
    await go('S-03 通用 5 项 + weight 差异字段', async function () {
      const r = await summary(tA, '?metric_type=weight');
      ok('S-03 HTTP 200', r.s === 200, 'HTTP ' + r.s);
      const d = D(r);
      okEq('S-03 顶层字段', Object.keys(d).sort(), ['metric_type', 'summary', 'unit', 'window']);
      okEq('S-03 unit = kg', d.unit, 'kg');
      const b = d.summary;
      okEq('S-03 average（4 个有记录日）', b.average, 71.5);
      okEq('S-03 change（首/末有记录日）', b.change,
           { from: 72, to: 71, delta: -1, from_date: dayStr(-6), to_date: dayStr(-2) });
      okEq('S-03 max（含日期）', b.max, { value: 72, date: dayStr(-6) });
      okEq('S-03 min（含日期）', b.min, { value: 71, date: dayStr(-2) });
      okEq('S-03 recorded_days', b.recorded_days,
           { recorded: 4, total: 7, percent: 57.1 });
      okEq('S-03 weight distance_to_target（最新体重 71 - 目标 68）', b.distance_to_target, 3);
      ok('S-03 weight reached_rate_percent 恒 null（G-07 口径）', b.reached_rate_percent === null,
         show(b.reached_rate_percent));
    });

    await go('S-03 逐指标差异字段（bp / heart / glucose / sleep / water / sport / mood）', async function () {
      const bp = D(await summary(tA, '?metric_type=bp')).summary;
      okEq('S-03 bp average_systolic / average_diastolic', [bp.average_systolic, bp.average_diastolic], [125, 85]);
      okEq('S-03 bp measure_count（原始测量条数）', bp.measure_count, 2);
      okEq('S-03 bp max（含收缩/舒张）', bp.max, { systolic: 130, diastolic: 90, date: dayStr(-2) });
      okEq('S-03 bp min（含收缩/舒张）', bp.min, { systolic: 120, diastolic: 80, date: dayStr(-5) });
      ok('S-03 bp 无目标类型 -> reached_rate_percent null', bp.reached_rate_percent === null);

      const hr = D(await summary(tA, '?metric_type=heart')).summary;
      okEq('S-03 heart resting_average（仅 attr_1=resting）', hr.resting_average, 60);
      okEq('S-03 heart average', hr.average, 70);

      const gl = D(await summary(tA, '?metric_type=glucose')).summary;
      okEq('S-03 glucose average_fasting', gl.average_fasting, 6);
      okEq('S-03 glucose average_after_meal', gl.average_after_meal, 8);
      okEq('S-03 glucose measure_count', gl.measure_count, 3);

      const sl = D(await summary(tA, '?metric_type=sleep')).summary;
      okEq('S-03 sleep average_duration_hours', sl.average_duration_hours, 7.5);
      okEq('S-03 sleep average_quality', sl.average_quality, 4.5);
      okEq('S-03 sleep longest（含日期）', sl.longest, { value: 8.5, date: dayStr(-2) });
      okEq('S-03 sleep shortest（含日期）', sl.shortest, { value: 6.5, date: dayStr(-1) });
      okEq('S-03 sleep reached_rate_percent（2 天中 1 天 >= 8h）', sl.reached_rate_percent, 50.0);

      const wt = D(await summary(tA, '?metric_type=water')).summary;
      okEq('S-03 water average（有记录日日值均值）', wt.average, 1125);
      okEq('S-03 water daily_average_ml', wt.daily_average_ml, 1125);
      okEq('S-03 water reached_day_count（>= 2000 ml）', wt.reached_day_count, 1);
      okEq('S-03 water reached_rate_percent（1/4）', wt.reached_rate_percent, 25.0);
      okEq('S-03 water longest_streak_days', wt.longest_streak_days, 1);

      const sp = D(await summary(tA, '?metric_type=sport')).summary;
      okEq('S-03 sport total_minutes', sp.total_minutes, 75);
      okEq('S-03 sport daily_average_minutes', sp.daily_average_minutes, 75);
      okEq('S-03 sport session_count', sp.session_count, 2);
      okEq('S-03 sport reached_week_count（无目标）', sp.reached_week_count, 0);
      const seenWeeks = {};
      for (let i = 0; i < 7; i++) {
        const dd = dayOff(-i);
        const wd = (dd.getDay() + 6) % 7;
        dd.setDate(dd.getDate() - wd);
        seenWeeks[rawDate(dd)] = 1;
      }
      const nWeeks = Object.keys(seenWeeks).length;
      okEq('S-03 sport weekly_average_minutes = 75 / 窗口覆盖周一数',
           sp.weekly_average_minutes, 75 / nWeeks);

      const md = D(await summary(tA, '?metric_type=mood')).summary;
      okEq('S-03 mood average_score', md.average_score, 3);
      okEq('S-03 mood best_day（含日期）', md.best_day, { value: 4, date: dayStr(-2) });
      okEq('S-03 mood worst_day（含日期）', md.worst_day, { value: 2, date: dayStr(-1) });
      okEq('S-03 mood tag_distribution', md.tag_distribution,
           [{ tag: 'tired', count: 1 }, { tag: 'relaxed', count: 2 }]);
      ok('S-03 mood reached_rate_percent null（无心情目标）', md.reached_rate_percent === null);
    });

    await go('S-03 空窗口 / 窗口与 S-02 一致 / 参数校验', async function () {
      const empty = D(await summary(tA, '?metric_type=water&end=' + dayStr(-10)));
      okEq('S-03 空窗口 window 块', empty.window,
           { days: 7, start: dayStr(-16), end: dayStr(-10) });
      const b = empty.summary;
      ok('S-03 空窗口 average/change/max/min/reached_rate 全 null',
         b.average === null && b.change === null && b.max === null && b.min === null &&
         b.reached_rate_percent === null);
      okEq('S-03 空窗口 recorded_days', b.recorded_days, { recorded: 0, total: 7, percent: 0.0 });
      ok('S-03 空窗口计数类为 0 / 均值类为 null',
         b.daily_average_ml === null && b.reached_day_count === 0 && b.longest_streak_days === 0);

      const q = '?metric_type=weight&window=30';
      const tw = D(await trend(tA, q)).window;
      const sw = D(await summary(tA, q)).window;
      okEq('S-03 窗口规则与 S-02 完全一致（同参数 -> 同 window 块）', sw, tw);

      const r1 = await summary(tA, '');
      const r2 = await summary(tA, '?metric_type=xyz');
      const r3 = await summary(tA, '?metric_type=water&window=15');
      const r4 = await summary(tA, '?metric_type=water&end=abc');
      ok('S-03 参数校验 -> 400（缺 metric_type / 非法类型 / 非法窗口 / 非法日期）',
         r1.s === 400 && r2.s === 400 && r3.s === 400 && r4.s === 400,
         [r1.s, r2.s, r3.s, r4.s].join(','));
      const r5 = await summary(tA, '?metric_type=water&window=90');
      ok('S-03 window=90 -> 200', r5.s === 200, 'HTTP ' + r5.s);
    });

    /* ============================== 6. S-01 有数据 + 隔离 ============================== */
    await go('S-01 今日统计 / 最近 10 条 / goals[] 8 字段', async function () {
      await addRec(tA, { metric_type: 'weight', value_1: 70.8, recorded_at: nowS() });
      await addRec(tA, { metric_type: 'water', value_1: 500, recorded_at: nowS() });
      await addRec(tA, { metric_type: 'mood', value_1: 3, tags: ['focused'], recorded_at: nowS() });
      await addRec(tA, { metric_type: 'sleep', value_1: 4,
                         time_start: fmt(new Date(Date.now() - 7 * 3600 * 1000)),
                         recorded_at: nowS() });

      const r = await overview(tA);
      const d = D(r);
      ok('S-01 有数据 HTTP 200', r.s === 200, 'HTTP ' + r.s);
      okEq('S-01 today.record_count 仅统计今日', d.today.record_count, 4);
      okEq('S-01 metric_types_recorded 按 METRIC_TYPES 固定序',
           d.today.metric_types_recorded, ['weight', 'sleep', 'water', 'mood']);

      const recs = d.recent_records;
      ok('S-01 recent_records 固定上限 10 条', recs.length === 10, '实际 ' + recs.length);
      const stamps = recs.map(function (x) { return x.recorded_at; });
      const sorted = stamps.slice().sort().reverse();
      okEq('S-01 recent_records 按 recorded_at DESC', stamps, sorted);
      okEq('S-01 recent_records 元素恰 8 字段',
           Object.keys(recs[0]).sort(),
           ['id', 'metric_type', 'note', 'recorded_at', 'tags', 'time_start', 'unit', 'value_1']);

      let moodRec = null, sleepRec = null;
      for (let i = 0; i < recs.length; i++) {
        if (!moodRec && recs[i].metric_type === 'mood') { moodRec = recs[i]; }
        if (!sleepRec && recs[i].metric_type === 'sleep') { sleepRec = recs[i]; }
      }
      ok('S-01 mood 记录带 tags（来自 record_tag）',
         moodRec !== null && Array.isArray(moodRec.tags) && moodRec.tags.indexOf('focused') >= 0,
         moodRec ? show(moodRec.tags) : '未找到 mood 记录');
      ok('S-01 sleep 记录带 time_start 且 unit = score',
         sleepRec !== null && sleepRec.time_start !== null && sleepRec.unit === 'score',
         sleepRec ? show(sleepRec.time_start) + ' / ' + sleepRec.unit : '未找到 sleep 记录');

      const goals = d.goals;
      okEq('S-01 goals[] 按 goal_type ASC（sleep < water < weight）',
           goals.map(function (g) { return g.goal_type; }), ['sleep', 'water', 'weight']);
      let gf = true, gfd = '';
      for (let i = 0; i < goals.length; i++) {
        if (!eq(Object.keys(goals[i]).sort(),
                ['current_value', 'goal_id', 'goal_type', 'is_reached', 'progress_percent',
                 'remaining_text', 'target_value', 'unit'])) {
          gf = false; gfd = show(Object.keys(goals[i]).sort());
        }
      }
      ok('S-01 goals[] 每项恰 8 字段（只读复用 G-07）', gf, gfd);

      let waterG = null;
      for (let i = 0; i < goals.length; i++) { if (goals[i].goal_type === 'water') { waterG = goals[i]; } }
      ok('S-01 water 目标完成度（今日 500 / 2000）',
         waterG !== null && waterG.target_value === 2000 && waterG.current_value === 500 &&
         waterG.progress_percent === 25.0 && waterG.is_reached === false,
         waterG ? show(waterG) : 'null');
    });

    await go('跨用户隔离（对端 acctest02 零泄漏）', async function () {
      const ov = D(await overview(tB));
      ok('隔离：对端 S-01 今日记录数 0 / goals 空 / recent 空',
         ov.today.record_count === 0 && ov.goals.length === 0 && ov.recent_records.length === 0,
         'count=' + ov.today.record_count + ' goals=' + ov.goals.length);
      const tr = D(await trend(tB, '?metric_type=water'));
      ok('隔离：对端 S-02 water points 为空', tr.points.length === 0, show(tr.points));
      ok('隔离：对端 S-02 insufficient_data = true', tr.insufficient_data === true);
      const sm = D(await summary(tB, '?metric_type=water')).summary;
      ok('隔离：对端 S-03 average null / recorded 0',
         sm.average === null && sm.recorded_days.recorded === 0, show(sm.recorded_days));
    });

    /* ============================== 7. 软删过滤 ============================== */
    await go('软删过滤（is_deleted=1 不参与聚合）', async function () {
      const before = await addRec(tA, { metric_type: 'water', value_1: 700, recorded_at: stamp(-4, 9, 0, 0) });
      await addRec(tA, { metric_type: 'water', value_1: 300, recorded_at: stamp(-4, 21, 0, 0) });
      const p0 = at(D(await trend(tA, '?metric_type=water')).points, dayStr(-4));
      okEq('软删前：d-4 当日累计 1000', p0, { date: dayStr(-4), total_ml: 1000 });

      const del = await call('DELETE', '/records/' + before, undefined, tA);
      ok('软删请求 200', del.s === 200, 'HTTP ' + del.s);
      const p1 = at(D(await trend(tA, '?metric_type=water')).points, dayStr(-4));
      okEq('软删后：d-4 当日累计降为 300（被删记录不参与聚合）',
           p1, { date: dayStr(-4), total_ml: 300 });
    });

    /* ============================== 8. 收尾清理 ============================== */
    console.log('\n清理本次测试数据（仅 acctest01 / acctest02 范围）...');
    const c1 = await purge(tA);
    const c2 = await purge(tB);
    console.log('清理完成：本端 ' + c1 + ' 条、对端 ' + c2 + ' 条');

    await go('收尾自证（清理后回到空态）', async function () {
      const d = D(await overview(tA));
      ok('收尾：本端回到空态（0 记录 / 0 目标）',
         d.today.record_count === 0 && d.goals.length === 0 && d.recent_records.length === 0,
         'count=' + d.today.record_count + ' goals=' + d.goals.length);
      const tr = D(await trend(tA, '?metric_type=water'));
      ok('收尾：本端 S-02 无数据点', tr.points.length === 0, show(tr.points));
    });
  } catch (e) {
    R.push('[FAIL] 顶层异常：' + (e && e.message));
    console.error(e);
  } finally {
    const bad = R.filter(function (x) { return x.indexOf('[OK]') !== 0; });
    console.log('\n================ 结果明细 ================');
    for (let i = 0; i < R.length; i++) { console.log(R[i]); }
    console.log('==========================================');
    console.log('合计 ' + (R.length - bad.length) + '/' + R.length + ' 通过，' + bad.length + ' 项失败');
    if (bad.length) { console.log('失败项：'); for (let i = 0; i < bad.length; i++) { console.log('  ' + bad[i]); } }
    try {
      window.__acc5 = { R: R, tA: tA, tB: tB, UA: UA, UB: UB,
                        newRecs: newRecs, newGoals: newGoals,
                        waterGoalId: waterGoalId, weightGoalId: weightGoalId };
      console.log('（已把本次结果挂到 window.__acc5，便于复查）');
    } catch (e2) { /* ignore */ }
  }
})();
