(async () => {
  const BASE = location.origin + '/api/v1';
  const PWD = 'Kangji2026';
  const UA = 'acctest01';
  const UB = 'acctest02';

  const R = [];
  const ok = function (name, cond, extra) {
    const tail = (extra === undefined || extra === null || extra === '') ? '' : '   → ' + extra;
    R.push((cond ? '✔' : '✘') + ' ' + name + tail);
  };
  const D = function (r) { return (r && r.b && r.b.data) || {}; };
  const ITEMS = function (r) { return D(r).items || []; };
  const codeOf = function (r) { return (r && r.b && r.b.code) || ''; };
  const pad = function (n) { return String(n).padStart(2, '0'); };
  const fmt = function (d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' +
           pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  };
  const nowS = function () { return fmt(new Date()); };
  const dayAgoS = function () {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    d.setHours(9, 0, 0, 0);
    return fmt(d);
  };
  const hoursAgoS = function (h) { return fmt(new Date(Date.now() - h * 3600 * 1000)); };

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

  /* 首次运行注册成功、再次运行账号已存在：两种情形都以「登录成功」为准，
     不因注册结果中断，也不删除 / 不修改任何账号。 */
  const boot = async function (u) {
    let reg = { s: 0, b: null };
    try {
      reg = await call('POST', '/auth/register', {
        username: u, password: PWD, agreement_version: 'v1.0', agreement_accepted: true
      });
    } catch (e) { reg = { s: 0, b: null }; }
    const regNote = (reg.s === 201 || reg.s === 200)
      ? '本次注册成功 HTTP ' + reg.s
      : '注册未成功 HTTP ' + reg.s + '（账号已存在时属正常），按已有账号继续';
    const r = await call('POST', '/auth/login', { username: u, password: PWD });
    if (r.s !== 200) {
      throw new Error('账号 ' + u + ' 登录失败 HTTP ' + r.s + '（注册结果 HTTP ' + reg.s + '）。' +
        '若此前手动改过该账号密码，请按第 4 步清理后重跑；本脚本不会删除或改动任何账号。');
    }
    console.log('账号 ' + u + ' 就绪：' + regNote + '；登录 HTTP 200');
    return D(r).tokens.access_token;
  };

  const go = async function (title, fn) {
    console.log('\n───── ' + title + ' ─────');
    try { await fn(); }
    catch (e) { R.push('✘ ' + title + ' 执行异常：' + (e && e.message)); }
  };

  let tA = null, tB = null;
  let water = {}, sleepG = {}, sportG = {}, weightG = {}, rebuilt = {};

  try {
    console.log('准备两个测试账号 acctest01 / acctest02 …');
    console.log('（若为重复运行，请先执行第 4 步清理，避免同类目标残留导致 409）');
    tA = await boot(UA);
    tB = await boot(UB);
    console.log('✅ 两个账号就绪');

    /* ── 铺垫：档案 + 健康记录（不计入 8 项验收）── */
    await go('[铺垫] 写入档案与健康记录', async function () {
      await call('PUT', '/profile', {
        nickname: '验收测试', gender: 1, birth_date: '1995-03-18',
        height_cm: 175.0, initial_weight_kg: 72.5
      }, tA);
      await call('PUT', '/profile', {
        nickname: '验收测试', gender: 1, birth_date: '1995-03-18', height_cm: 180.0
      }, tB);
      await call('POST', '/records', { metric_type: 'weight', value_1: 70.4, recorded_at: dayAgoS() }, tA);
      await call('POST', '/records', { metric_type: 'water', value_1: 1000, recorded_at: nowS() }, tA);
      await call('POST', '/records', { metric_type: 'water', value_1: 500, recorded_at: nowS() }, tA);
      await call('POST', '/records', { metric_type: 'sport', value_1: 30, attr_1: 'running', recorded_at: nowS() }, tA);
      await call('POST', '/records', { metric_type: 'sport', value_1: 20, attr_1: 'running', recorded_at: nowS() }, tA);
      await call('POST', '/records', {
        metric_type: 'sleep', value_1: 4, time_start: hoursAgoS(7.5), recorded_at: nowS()
      }, tA);
      console.log('已写入：体重 70.4（昨日）/ 饮水 1000+500（今日）/ 运动 30+20（本周）/ 睡眠 7.5 小时（今日）');
    });

    /* ── ① G-01 目标列表（空态 / 非法参数 / 未认证）── */
    await go('① G-01 目标列表（空态 / 非法参数 / 未认证）', async function () {
      let r = await call('GET', '/goals', undefined, tB);
      ok('G-01 无目标 → 返回 items: []（不是 404）',
         r.s === 200 && Array.isArray(D(r).items) && D(r).items.length === 0, 'HTTP ' + r.s);
      r = await call('GET', '/goals?goal_type=bp', undefined, tA);
      ok('G-01 非法 goal_type → 400 / code=INVALID_PARAM',
         r.s === 400 && codeOf(r) === 'INVALID_PARAM', 'HTTP ' + r.s + '  code=' + codeOf(r));
      r = await call('GET', '/goals');
      ok('G-01 未认证 → 401 / code=UNAUTHENTICATED',
         r.s === 401 && codeOf(r) === 'UNAUTHENTICATED', 'HTTP ' + r.s + '  code=' + codeOf(r));
    });

    /* ── ② G-02 创建目标 ── */
    await go('② G-02 创建目标', async function () {
      let r = await call('POST', '/goals', { goal_type: 'water', target_value: 2000 }, tA);
      water = D(r).goal || {};
      ok('G-02 water 创建成功（HTTP 201）', r.s === 201, 'HTTP ' + r.s);
      ok('G-02 响应中 period_type=daily 且 unit=ml（服务端决定）',
         water.period_type === 'daily' && water.unit === 'ml',
         String(water.period_type) + ' / ' + String(water.unit));
      ok('G-02 返回文案 = 目标已创建', !!r.b && r.b.message === '目标已创建');

      r = await call('POST', '/goals', { goal_type: 'water', target_value: 2500 }, tA);
      ok('G-02 同类目标已存在 → 409 / code=GOAL_TYPE_EXISTS',
         r.s === 409 && codeOf(r) === 'GOAL_TYPE_EXISTS', 'HTTP ' + r.s + '  code=' + codeOf(r));

      r = await call('POST', '/goals', {
        goal_type: 'sport', target_value: 150, attr_1: 'min', period_type: 'daily'
      }, tA);
      ok('G-02 period_type 与类型不符（sport 传 daily）→ 422', r.s === 422, 'HTTP ' + r.s);

      r = await call('POST', '/goals', { goal_type: 'sport', target_value: 150 }, tA);
      ok('G-02 sport 未传 attr_1 → 422 且 errors[] 含 field=attr_1',
         r.s === 422 && (r.b.errors || []).some(function (e) { return e.field === 'attr_1'; }),
         'HTTP ' + r.s);

      r = await call('POST', '/goals', { goal_type: 'sleep', target_value: 30 }, tA);
      ok('G-02 目标值不可能（sleep 30 小时）→ 422 硬拦截', r.s === 422, 'HTTP ' + r.s);

      /* 软提示前后各取一次 sleep 目标 id 集合，用「集合是否变化」判断本次是否落库，
         对「首次运行 / 重复运行（已有残留目标）」都成立。 */
      const sleepBefore = ITEMS(await call('GET', '/goals?goal_type=sleep', undefined, tA))
        .map(function (i) { return i.id; }).sort().join(',');
      r = await call('POST', '/goals', { goal_type: 'sleep', target_value: 20 }, tA);
      ok('G-02 超出常见范围 → 200 / code=SOFT_WARNING / requires_confirm=true',
         r.s === 200 && codeOf(r) === 'SOFT_WARNING' && D(r).requires_confirm === true,
         'HTTP ' + r.s + '  code=' + codeOf(r));
      ok('G-02 软提示响应带 warnings[]、且不带 errors[]',
         !!r.b && !('errors' in r.b) && Array.isArray(D(r).warnings) && D(r).warnings.length > 0);
      const sleepAfter = ITEMS(await call('GET', '/goals?goal_type=sleep', undefined, tA))
        .map(function (i) { return i.id; }).sort().join(',');
      ok('G-02 软提示未写入：GET /goals?goal_type=sleep 的 id 集合前后一致',
         sleepBefore === sleepAfter, '前=[' + sleepBefore + ']  后=[' + sleepAfter + ']');

      r = await call('POST', '/goals', { goal_type: 'sleep', target_value: 8 }, tA);
      sleepG = D(r).goal || {};
      ok('G-02 sleep 创建成功 + unit=hour + period_type=daily',
         r.s === 201 && sleepG.unit === 'hour' && sleepG.period_type === 'daily', 'HTTP ' + r.s);

      r = await call('POST', '/goals', { goal_type: 'sport', target_value: 150, attr_1: 'min' }, tA);
      sportG = D(r).goal || {};
      ok('G-02 sport(min) 创建成功 + unit=min + period_type=weekly',
         r.s === 201 && sportG.unit === 'min' && sportG.period_type === 'weekly', 'HTTP ' + r.s);

      r = await call('POST', '/goals', {
        goal_type: 'weight', target_value: 66.0, auto_start_weight: true, target_date: '2026-12-31'
      }, tA);
      weightG = D(r).goal || {};
      ok('G-02 weight 创建成功 + 起始体重自动取最近体重 70.4',
         r.s === 201 && weightG.start_weight_kg === 70.4,
         'HTTP ' + r.s + '  起始体重=' + String(weightG.start_weight_kg));

      ok('G-02 weight 目标值 == 起始体重 → 422',
         (await call('POST', '/goals', {
           goal_type: 'weight', target_value: 70.4, start_weight_kg: 70.4
         }, tA)).s === 422);
      r = await call('POST', '/goals', {
        goal_type: 'water', target_value: 2000, user_id: 1
      }, tA);
      ok('G-02 请求体携带 user_id → 400 / code=INVALID_PARAM',
         r.s === 400 && codeOf(r) === 'INVALID_PARAM', 'HTTP ' + r.s + '  code=' + codeOf(r));
    });

    /* ── ① G-01 目标列表（有数据 / 排序 / 过滤 / 字段集）── */
    await go('① G-01 目标列表（有数据 / 排序 / 过滤 / 字段集）', async function () {
      const r = await call('GET', '/goals', undefined, tA);
      const items = ITEMS(r);
      const types = items.map(function (i) { return i.goal_type; }).join(',');
      ok('G-01 返回 4 类目标，且按 goal_type 升序',
         r.s === 200 && types === 'sleep,sport,water,weight', 'HTTP ' + r.s + '  ' + types);
      ok('G-01 条目响应字段中不含 is_deleted / deleted_marker / deleted_at',
         items.length > 0 && items.every(function (i) {
           return !('is_deleted' in i) && !('deleted_marker' in i) && !('deleted_at' in i);
         }));
      ok('G-01 status_text 仅为中性值 ongoing / paused / archived',
         items.every(function (i) {
           return ['ongoing', 'paused', 'archived'].indexOf(i.status_text) >= 0;
         }));
      ok('G-01 goal_type=water 过滤生效',
         ITEMS(await call('GET', '/goals?goal_type=water', undefined, tA))
           .map(function (i) { return i.goal_type; }).join(',') === 'water');
      ok('G-01 include_history=true 可用（HTTP 200）',
         (await call('GET', '/goals?include_history=true', undefined, tA)).s === 200);
    });

    /* ── ⑦ G-07 目标完成度 ── */
    await go('⑦ G-07 目标完成度（四类算法 / 达标率 / 窗口 / 404）', async function () {
      const r = await call('GET', '/goals/progress', undefined, tA);
      const P = {};
      ITEMS(r).forEach(function (i) { P[i.goal_type] = i; });
      ok('G-07 200 且返回 4 条完成度',
         r.s === 200 && Object.keys(P).length === 4, 'HTTP ' + r.s);
      ok('G-07 water 当日 1500/2000 = 75.0，remaining_text = 还差 500 ml',
         !!P.water && P.water.current_value === 1500 && P.water.progress_percent === 75.0 &&
           P.water.remaining_text === '还差 500 ml',
         P.water ? (String(P.water.current_value) + ' / ' + String(P.water.progress_percent) + '% / ' +
                    String(P.water.remaining_text)) : 'missing');
      ok('G-07 sport 本周 50/150 = 33.3，period_label = this_week',
         !!P.sport && P.sport.current_value === 50 && P.sport.progress_percent === 33.3 &&
           P.sport.period_label === 'this_week',
         P.sport ? (String(P.sport.current_value) + ' / ' + String(P.sport.progress_percent) + '%') : 'missing');
      ok('G-07 weight (70.4→66.0) = 0.0%，rate === null，period_label = overall',
         !!P.weight && P.weight.progress_percent === 0.0 && P.weight.rate === null &&
           P.weight.period_label === 'overall',
         P.weight ? (String(P.weight.progress_percent) + '%  rate=' + String(P.weight.rate)) : 'missing');
      ok('G-07 sleep 当日派生 7.5/8 = 93.8',
         !!P.sleep && P.sleep.current_value === 7.5 && P.sleep.progress_percent === 93.8,
         P.sleep ? (String(P.sleep.current_value) + ' / ' + String(P.sleep.progress_percent) + '%') : 'missing');
      ok('G-07 water 的 rate 为对象（daily 有达标率），weight 的 rate === null',
         !!P.water && !!P.water.rate && typeof P.water.rate === 'object' &&
           !!P.weight && P.weight.rate === null);
      ok('G-07 rate_window=7 生效（window_days = 7）',
         (((ITEMS(await call('GET', '/goals/progress?rate_window=7', undefined, tA))[0] || {})
           .rate) || {}).window_days === 7);
      const rw = await call('GET', '/goals/progress?rate_window=45', undefined, tA);
      ok('G-07 rate_window 非法（45）→ 400 / code=INVALID_PARAM',
         rw.s === 400 && codeOf(rw) === 'INVALID_PARAM', 'HTTP ' + rw.s + '  code=' + codeOf(rw));
      ok('G-07 goal_id 不存在 → 404',
         (await call('GET', '/goals/progress?goal_id=99999999', undefined, tA)).s === 404);
      ok('G-07 跨用户 goal_id → 404（跨用户不可访问）',
         (await call('GET', '/goals/progress?goal_id=' + water.id, undefined, tB)).s === 404);
    });

    /* ── ③ G-03 修改目标 ── */
    await go('③ G-03 修改目标', async function () {
      const r = await call('PATCH', '/goals/' + water.id, { target_value: 2500 }, tA);
      ok('G-03 修改目标值成功（HTTP 200，目标值变为 2500）',
         r.s === 200 && (D(r).goal || {}).target_value === 2500,
         'HTTP ' + r.s + '  目标值=' + String((D(r).goal || {}).target_value));
      ok('G-03 请求中出现 goal_type → 422（不允许改类型）',
         (await call('PATCH', '/goals/' + water.id, {
           goal_type: 'water', target_value: 2500
         }, tA)).s === 422);
      ok('G-03 试图修改 start_weight_kg → 422',
         (await call('PATCH', '/goals/' + weightG.id, { start_weight_kg: 70.0 }, tA)).s === 422);
      ok('G-03 跨用户修改 → 404',
         (await call('PATCH', '/goals/' + water.id, { target_value: 2500 }, tB)).s === 404);
    });

    /* ── ④ G-04 暂停 ／ ⑤ G-05 恢复 ── */
    await go('④ G-04 暂停目标 ／ ⑤ G-05 恢复目标', async function () {
      let r = await call('POST', '/goals/' + water.id + '/pause', undefined, tA);
      ok('G-04 暂停成功（200，changed=true，status=0）',
         r.s === 200 && D(r).changed === true && D(r).status === 0, 'HTTP ' + r.s);
      ok('G-04 重复暂停（幂等）→ changed=false',
         D(await call('POST', '/goals/' + water.id + '/pause', undefined, tA)).changed === false);
      ok('G-04 列表中该目标 status_text = paused（中性表达）',
         (ITEMS(await call('GET', '/goals', undefined, tA))
           .filter(function (i) { return i.id === water.id; })[0] || {}).status_text === 'paused');
      ok('G-04 include_paused=false 时暂停目标被过滤',
         ITEMS(await call('GET', '/goals?include_paused=false', undefined, tA))
           .every(function (i) { return i.id !== water.id; }));
      r = await call('POST', '/goals/' + water.id + '/resume', undefined, tA);
      ok('G-05 恢复成功（200，changed=true）',
         r.s === 200 && D(r).changed === true, 'HTTP ' + r.s);
      ok('G-05 重复恢复（幂等）→ changed=false',
         D(await call('POST', '/goals/' + water.id + '/resume', undefined, tA)).changed === false);
      ok('G-04/G-05 跨用户操作 → 404',
         (await call('POST', '/goals/' + water.id + '/pause', undefined, tB)).s === 404);
    });

    /* ── ⑦ D-G3 暂停目标仍返回完整完成度 ── */
    await go('⑦ D-G3 暂停目标仍返回完整完成度', async function () {
      await call('POST', '/goals/' + water.id + '/pause', undefined, tA);
      const r = await call('GET', '/goals/progress?goal_id=' + water.id, undefined, tA);
      const p = ITEMS(r)[0] || {};
      ok('★ D-G3 暂停目标 status=0，完成度仍完整返回（1500/2500 = 60.0%）',
         p.status === 0 && p.current_value === 1500 && p.progress_percent === 60.0,
         'status=' + String(p.status) + '  current=' + String(p.current_value) +
         '  ' + String(p.progress_percent) + '%');
      await call('POST', '/goals/' + water.id + '/resume', undefined, tA);
    });

    /* ── ⑥ G-06 删除目标（软删）── */
    await go('⑥ G-06 删除目标（软删）', async function () {
      let r = await call('DELETE', '/goals/' + sleepG.id, undefined, tA);
      ok('G-06 删除成功（200，deleted_count=1）',
         r.s === 200 && D(r).deleted_count === 1, 'HTTP ' + r.s);
      ok('G-06 删除后默认列表（不传 include_history）不再返回该目标',
         ITEMS(await call('GET', '/goals', undefined, tA))
           .every(function (i) { return i.id !== sleepG.id; }));
      const hist = ITEMS(await call('GET', '/goals?include_history=true', undefined, tA))
        .filter(function (i) { return i.id === sleepG.id; });
      ok('G-06 include_history=true 仍可查到该目标，且 status_text=archived',
         hist.length === 1 && hist[0].status_text === 'archived', '历史条数=' + String(hist.length));
      r = await call('DELETE', '/goals/' + sleepG.id, undefined, tA);
      ok('G-06 重复删除 → 404 / code=RESOURCE_NOT_FOUND',
         r.s === 404 && codeOf(r) === 'RESOURCE_NOT_FOUND', 'HTTP ' + r.s + '  code=' + codeOf(r));
      ok('G-06 历史目标不可编辑 → 404',
         (await call('PATCH', '/goals/' + sleepG.id, { target_value: 9 }, tA)).s === 404);
      r = await call('POST', '/goals', { goal_type: 'sleep', target_value: 8 }, tA);
      rebuilt = D(r).goal || {};
      ok('G-06 同类型目标可重新创建（201），且新 id 与旧 id 不同',
         r.s === 201 && rebuilt.id !== sleepG.id,
         'HTTP ' + r.s + '  旧 id=' + String(sleepG.id) + '  新 id=' + String(rebuilt.id));
      ok('G-06 跨用户删除 → 404',
         (await call('DELETE', '/goals/' + sleepG.id, undefined, tB)).s === 404);
    });

    /* ── ⑧ 用户隔离 / user_id 注入 ── */
    await go('⑧ 用户隔离 / user_id 注入', async function () {
      let r = await call('GET', '/goals', undefined, tB);
      ok('隔离：对端 GET /goals 看不到本端任何目标（列表为空）',
         ITEMS(r).length === 0, '对端条数=' + String(ITEMS(r).length));
      r = await call('GET', '/goals?user_id=1', undefined, tA);
      ok('隔离：查询参数注入 user_id → 400 / code=INVALID_PARAM',
         r.s === 400 && codeOf(r) === 'INVALID_PARAM', 'HTTP ' + r.s + '  code=' + codeOf(r));
      r = await call('POST', '/goals', {
        goal_type: 'water', target_value: 2000, user_id: 1
      }, tA);
      ok('隔离：请求体注入 user_id → 400 / code=INVALID_PARAM',
         r.s === 400 && codeOf(r) === 'INVALID_PARAM', 'HTTP ' + r.s + '  code=' + codeOf(r));
      console.log('提示：对端修改 / 删除 / 暂停本端目标均返回 404，已在上文各项中分别断言。');
    });

  } catch (e) {
    R.push('✘ 脚本中途异常：' + (e && e.message));
  } finally {
    console.log('\n════════ 验收结果汇总 ════════');
    console.log(R.join('\n'));
    const bad = R.filter(function (x) { return x.indexOf('✘') === 0; }).length;
    console.log('\n合计 ' + (R.length - bad) + '/' + R.length + ' 通过，' + bad + ' 项失败');
    console.log('\n本脚本只断言 API 可证事实；is_deleted / deleted_at / deleted_marker 等库内字段');
    console.log('不在此脚本结论内，请按下述 id 在第 3 步用只读 SELECT 直查确认。');
    console.log('  本端账号 = ' + UA);
    console.log('  被软删的 sleep 目标 id = ' + String(sleepG.id === undefined ? '（未获取）' : sleepG.id));
    console.log('  重建后的 sleep 目标 id = ' + String(rebuilt.id === undefined ? '（未获取）' : rebuilt.id));
    if (bad) {
      console.log('\n失败明细：');
      R.filter(function (x) { return x.indexOf('✘') === 0; })
       .forEach(function (x) { console.log('  ' + x); });
    }
    try {
      window.__acc = { R: R, tA: tA, tB: tB, UA: UA, UB: UB,
                       water: water, sleepG: sleepG, sportG: sportG,
                       weightG: weightG, rebuilt: rebuilt };
      console.log('\n（已把本次结果挂到 window.__acc，便于复查）');
    } catch (e2) { }
  }
})();
