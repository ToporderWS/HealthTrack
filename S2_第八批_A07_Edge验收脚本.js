/* ============================================================================
 * S2 第八批 A-07（注销账号）—— 浏览器 Edge 一键验收脚本
 * ----------------------------------------------------------------------------
 * 用法（**同源**，无 CORS）：
 *   1) 先启动后端：cd backend && .venv/Scripts/python.exe wsgi.py
 *   2) 浏览器打开 http://127.0.0.1:5000/api/v1/health
 *   3) F12 -> Console；如提示“请勿粘贴”，先手打  allow pasting  回车
 *   4) 从下面的【开始行】下一行起整段复制，粘到 Console 回车
 *
 * 【开始行】= 本行
 * ============================================================================
 *
 * 设计约束（本机硬约束，务必遵守）：
 *   - **零反引号**：不使用 ES6 模板字符串，全部改为字符串拼接
 *     （“查看 -> 复制”链路会吞掉反引号，导致 missing ) after argument list）。
 *   - **GET/HEAD 不携带 body**：fetch 对 GET 带 body 会直接抛 TypeError；
 *     需要投递 JSON 体时一律换成 POST 投同一路径。DELETE 可安全携带 body。
 *   - 断言只描述“API 可证事实”；点名错误码时**同时**校验 code；
 *     判 null 用 === null，不用 !x。
 *   - 分组用 async 函数 + try/catch：**块内抛异常 = 该块剩余断言不执行、只压入 1 条 FAIL**
 *     （因此报告里的“断言总数”必须在无异常时读取）。
 *   - **A-07 是破坏性操作**：只对本脚本自建的 tstb8edgea / tstb8edgeb 执行注销，
 *     绝不对任何非测试账号执行；收尾请用素材 B 第 3 段 SQL 清理这两个账号。
 *   - 建议先执行素材 B 第 1 段 SQL（清空 tstb8edge* 历史残留），保证账目可复现。
 *
 * A-07 冻结契约口径（本脚本据此断言）：
 *   - 路径与方法：DELETE /api/v1/users/me（与 A-06 GET 同路径不同方法）
 *   - 三重确认：有效登录态 + password + confirm_text === '注销账号'
 *     （**不含** acknowledge_irreversible；不带任何范围扩展参数）
 *   - 成功：200 + data 恰 1 键 account_closed === true + 文案 '账号已注销'
 *   - 错误：缺 confirm_text -> 422 VALIDATION_FAILED + errors[].code === REQUIRED
 *           错 confirm_text -> 422 VALIDATION_FAILED + errors[].code === INVALID_FORMAT
 *           缺 / 空 password -> 422 VALIDATION_FAILED
 *           密码错误        -> 422 PASSWORD_INVALID（**不累计、不锁定、无 429**）
 *           未认证 / 重复提交 -> 401（天然幂等）
 */
(function () {
  'use strict';

  var BASE = location.origin + '/api/v1';
  var PWD = 'Kangji2026';
  var UA = 'tstb8edgea';   /* 被测主体（最终被注销） */
  var UB = 'tstb8edgeb';   /* 隔离对端（必须全程不受影响） */

  /* 冻结口径常量 */
  var CONFIRM_TEXT = '注销账号';
  var D02_CONFIRM_TEXT = '确认删除';
  var CLOSED_KEYS = ['account_closed'];
  var CLOSED_MESSAGE = '账号已注销';
  var ENVELOPE_KEYS = ['code', 'data', 'message', 'request_id'];
  var REC_LIST_KEYS = ['has_more', 'items', 'next_cursor'];

  var results = [];
  var fails = [];
  var tokenA = '';
  var tokenB = '';
  var refreshA = '';
  var recIdsA = [];

  function say(text) {
    console.log(text);
  }

  function ok(name, cond, detail) {
    var pass = cond === true;
    results.push({ name: name, pass: pass, detail: detail || '' });
    if (!pass) {
      fails.push(name + (detail ? '   -> ' + detail : ''));
    }
    say('  ' + (pass ? 'PASS' : 'FAIL') + '  ' + name + (pass ? '' : '   -> ' + detail));
    return pass;
  }

  function okEq(name, actual, expect) {
    var a = JSON.stringify(actual);
    var e = JSON.stringify(expect);
    return ok(name, a === e, '实际 ' + a + ' / 期望 ' + e);
  }

  function sortedKeys(obj) {
    return Object.keys(obj || {}).sort();
  }

  function pad2(n) {
    return (n < 10 ? '0' : '') + n;
  }

  /* 本地墙上时间 */
  function stamp(dayOffset, hour, minute) {
    var d = new Date();
    d.setDate(d.getDate() + dayOffset);
    d.setHours(hour, minute, 0, 0);
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + ' ' +
           pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':00';
  }

  /* ── HTTP：JSON 调用（GET/HEAD 一律不带 body） ─────────────────────────── */
  function call(method, path, body, token, extraHeaders) {
    var opt = { method: method, headers: {} };
    var k;
    if (extraHeaders) {
      for (k in extraHeaders) {
        if (Object.prototype.hasOwnProperty.call(extraHeaders, k)) {
          opt.headers[k] = extraHeaders[k];
        }
      }
    }
    if (token) {
      opt.headers.Authorization = 'Bearer ' + token;
    }
    if (body !== undefined && body !== null && method !== 'GET' && method !== 'HEAD') {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    return fetch(BASE + path, opt).then(function (resp) {
      return resp.text().then(function (text) {
        var parsed = null;
        try {
          parsed = text ? JSON.parse(text) : null;
        } catch (e) {
          parsed = null;
        }
        return { status: resp.status, body: parsed, text: text };
      });
    });
  }

  function dataOf(body) {
    return (body && body.data) || {};
  }

  function codeOf(body) {
    return (body && body.code) || '';
  }

  function msgOf(body) {
    return (body && body.message) || '';
  }

  function errorsOf(body) {
    var e = body && body.errors;
    return Array.isArray(e) ? e : [];
  }

  /* A-07 请求体构造（confirm_text 必填 + password 必填 + 可选 client_time） */
  function payload(password, confirmText) {
    return { password: password, confirm_text: confirmText };
  }

  function boot(username) {
    return call('POST', '/auth/register', { username: username, password: PWD,
                                            agreement_version: 'v1.0',
                                            agreement_accepted: true })
      .then(function () {
        return call('POST', '/auth/login', { username: username, password: PWD });
      })
      .then(function (r) {
        var t = dataOf(r.body).tokens || {};
        return { access: t.access_token || '', refresh: t.refresh_token || '' };
      });
  }

  /* 只软删（R-07）账号已有的活跃记录，使后续“活跃条数”断言可复现 */
  async function softDeleteAll(token) {
    var r = await call('GET', '/records?limit=100', null, token);
    var items = dataOf(r.body).items || [];
    var n = 0;
    for (var i = 0; i < items.length; i++) {
      var d = await call('DELETE', '/records/' + items[i].id, null, token);
      if (d.status === 200) {
        n++;
      }
    }
    return n;
  }

  /* ══════════════════════════════════════════════════════════════════════ */
  async function group0Connect() {
    var h = await call('GET', '/health');
    ok('连通性：GET /api/v1/health 200 OK', h.status === 200 && codeOf(h.body) === 'OK',
       'HTTP ' + h.status + ' ' + codeOf(h.body));

    var u1 = await call('DELETE', '/users/me', payload(PWD, CONFIRM_TEXT));
    ok('A-07 无 Token -> 401 UNAUTHENTICATED',
       u1.status === 401 && codeOf(u1.body) === 'UNAUTHENTICATED',
       'HTTP ' + u1.status + ' ' + codeOf(u1.body));

    var u2 = await call('DELETE', '/users/me', payload(PWD, CONFIRM_TEXT), 'not-a-real-token');
    ok('A-07 坏 Token -> 401 UNAUTHENTICATED',
       u2.status === 401 && codeOf(u2.body) === 'UNAUTHENTICATED',
       'HTTP ' + u2.status + ' ' + codeOf(u2.body));

    var q = await call('DELETE', '/users/me?user_id=1', payload(PWD, CONFIRM_TEXT), tokenA);
    ok('A-07 query 携带 user_id -> 400 INVALID_PARAM（全局守卫）',
       q.status === 400 && codeOf(q.body) === 'INVALID_PARAM',
       'HTTP ' + q.status + ' ' + codeOf(q.body));

    var b = await call('DELETE', '/users/me',
                       { password: PWD, confirm_text: CONFIRM_TEXT, user_id: 1 }, tokenA);
    ok('A-07 body 携带 user_id -> 400 INVALID_PARAM（全局守卫）',
       b.status === 400 && codeOf(b.body) === 'INVALID_PARAM',
       'HTTP ' + b.status + ' ' + codeOf(b.body));

    var e = await call('GET', '/users/me', null, tokenA);
    okEq('统一 envelope：成功响应恰 4 键（code/data/message/request_id）',
         sortedKeys(e.body), ENVELOPE_KEYS);
    ok('统一 envelope：request_id 非空（X-Request-Id 已回写）',
       typeof (e.body || {}).request_id === 'string' && e.body.request_id.length > 0,
       String((e.body || {}).request_id));
  }

  async function group1Seed() {
    var nA = await softDeleteAll(tokenA);
    var nB = await softDeleteAll(tokenB);
    ok('预清理：A 端历史活跃记录已软删 ' + nA + ' 条 / B 端 ' + nB + ' 条（保证可复现）',
       true);

    var payloads = [
      { metric_type: 'weight', value_1: 70.50, recorded_at: stamp(-2, 9, 0) },
      { metric_type: 'water', value_1: 500, recorded_at: stamp(-1, 9, 0) },
      { metric_type: 'mood', value_1: 4, tags: ['relaxed', 'focused'],
        recorded_at: stamp(-1, 10, 0) }
    ];
    for (var i = 0; i < payloads.length; i++) {
      var r = await call('POST', '/records', payloads[i], tokenA);
      if (r.status !== 201) {
        throw new Error('R-01 写入失败 HTTP ' + r.status + ' ' + codeOf(r.body));
      }
      recIdsA.push(dataOf(r.body).record.id);
    }
    ok('造数：A 端 3 条活跃记录（weight/water/mood+tags）', recIdsA.length === 3,
       String(recIdsA.length));

    var v = await call('POST', '/records',
                       { metric_type: 'water', value_1: 700, recorded_at: stamp(-3, 9, 0) }, tokenA);
    var victim = dataOf(v.body).record.id;
    var del = await call('DELETE', '/records/' + victim, null, tokenA);
    ok('造数：A 端软删 1 条 water（HTTP 200）', del.status === 200, 'HTTP ' + del.status);

    var lr = await call('GET', '/records?limit=100', null, tokenA);
    var items = dataOf(lr.body).items || [];
    okEq('造数核对：A 端活跃记录恰 3 条（软删 1 条不计入）', items.length, 3);
    ok('造数核对：列表响应恰 3 键（items/next_cursor/has_more，无 total）',
       sortedKeys(dataOf(lr.body)).join(',') === REC_LIST_KEYS.join(','),
       sortedKeys(dataOf(lr.body)).join(','));

    var p = await call('PUT', '/profile', {
      nickname: '冒烟八甲', gender: 1, birth_date: '1990-05-20',
      height_cm: 175, initial_weight_kg: null, blood_type: 'A',
      medical_history: '无', allergy_history: null, medication_notes: null,
      acknowledge_warnings: true
    }, tokenA);
    ok('造数：P-02 档案 3/6 健康字段 + 昵称/性别/出生日期', p.status === 200,
       'HTTP ' + p.status + ' ' + codeOf(p.body));

    var g1 = await call('POST', '/goals',
                        { goal_type: 'water', target_value: 2000, acknowledge_warnings: true },
                        tokenA);
    ok('造数：G-02 建 water 目标 -> 201', g1.status === 201,
       'HTTP ' + g1.status + ' ' + codeOf(g1.body));

    var g2 = await call('POST', '/goals',
                        { goal_type: 'sport', attr_1: 'count', target_value: 3,
                          acknowledge_warnings: true }, tokenA);
    var sportId = (dataOf(g2.body).goal || {}).id;
    ok('造数：G-02 建 sport 目标 -> 201', g2.status === 201 && !!sportId,
       'HTTP ' + g2.status + ' id=' + sportId);

    var g3 = await call('POST', '/goals/' + sportId + '/pause', null, tokenA);
    ok('造数：G-04 暂停 sport 目标 -> 200', g3.status === 200,
       'HTTP ' + g3.status + ' ' + codeOf(g3.body));

    var bb = await call('POST', '/records',
                        { metric_type: 'weight', value_1: 60, recorded_at: stamp(-1, 8, 0) },
                        tokenB);
    ok('造数：B 端 1 条活跃记录（隔离对照）', bb.status === 201, 'HTTP ' + bb.status);
  }

  async function group2ConfirmNegative() {
    var m = await call('DELETE', '/users/me', { password: PWD }, tokenA);
    var er = errorsOf(m.body);
    ok('A-07 缺 confirm_text -> 422 VALIDATION_FAILED + errors[].code === REQUIRED',
       m.status === 422 && codeOf(m.body) === 'VALIDATION_FAILED' &&
       er.length === 1 && er[0].field === 'confirm_text' && er[0].code === 'REQUIRED',
       'HTTP ' + m.status + ' ' + JSON.stringify(m.body));

    var w = await call('DELETE', '/users/me', payload(PWD, '注销帐号'), tokenA);
    var er2 = errorsOf(w.body);
    ok('A-07 确认文字错别字 -> 422 + errors[].code === INVALID_FORMAT',
       w.status === 422 && codeOf(w.body) === 'VALIDATION_FAILED' &&
       er2.length === 1 && er2[0].field === 'confirm_text' && er2[0].code === 'INVALID_FORMAT',
       'HTTP ' + w.status + ' ' + JSON.stringify(w.body));

    var d2 = await call('DELETE', '/users/me', payload(PWD, D02_CONFIRM_TEXT), tokenA);
    ok('A-07 复用 D-02 的「确认删除」-> 422（**不得**混用文案）',
       d2.status === 422 && codeOf(d2.body) === 'VALIDATION_FAILED',
       'HTTP ' + d2.status + ' ' + codeOf(d2.body));

    var em = await call('DELETE', '/users/me', payload(PWD, ''), tokenA);
    ok('A-07 确认文字为空串 -> 422 VALIDATION_FAILED（不得误判为缺失）',
       em.status === 422 && codeOf(em.body) === 'VALIDATION_FAILED',
       'HTTP ' + em.status + ' ' + codeOf(em.body));

    var np = await call('DELETE', '/users/me', { confirm_text: CONFIRM_TEXT }, tokenA);
    var er3 = errorsOf(np.body);
    ok('A-07 缺 password -> 422 + errors[].field === password / code === REQUIRED',
       np.status === 422 && codeOf(np.body) === 'VALIDATION_FAILED' &&
       er3.length === 1 && er3[0].field === 'password' && er3[0].code === 'REQUIRED',
       'HTTP ' + np.status + ' ' + JSON.stringify(np.body));

    var bp = await call('DELETE', '/users/me',
                        { password: '   ', confirm_text: CONFIRM_TEXT }, tokenA);
    ok('A-07 password 为空白串 -> 422 VALIDATION_FAILED',
       bp.status === 422 && codeOf(bp.body) === 'VALIDATION_FAILED',
       'HTTP ' + bp.status + ' ' + codeOf(bp.body));

    /* acknowledge_irreversible 既非必需、也不改变校验结果（A-07 冻结契约不含该参数） */
    var ai = await call('DELETE', '/users/me',
                        { password: PWD, confirm_text: 'x', acknowledge_irreversible: true },
                        tokenA);
    ok('A-07 acknowledge_irreversible 非必需且不改变校验（仍 422 VALIDATION_FAILED）',
       ai.status === 422 && codeOf(ai.body) === 'VALIDATION_FAILED',
       'HTTP ' + ai.status + ' ' + codeOf(ai.body));

    var cc = await call('DELETE', '/users/me',
                        { password: PWD, confirm_text: 'x', client_time: stamp(0, 12, 0) },
                        tokenA);
    ok('A-07 client_time 不参与业务判定（确认文字仍被校验 -> 422）',
       cc.status === 422 && codeOf(cc.body) === 'VALIDATION_FAILED',
       'HTTP ' + cc.status + ' ' + codeOf(cc.body));

    var lr = await call('GET', '/records?limit=100', null, tokenA);
    ok('失败路径后 A 端数据**未变**：活跃记录仍 3 条',
       ((dataOf(lr.body).items) || []).length === 3,
       String(((dataOf(lr.body).items) || []).length));
    var me = await call('GET', '/users/me', null, tokenA);
    ok('失败路径后 A 端账号**仍在**（GET /users/me 200）', me.status === 200,
       'HTTP ' + me.status);
  }

  async function group3WrongPassword() {
    var first = null;
    var last = null;
    for (var i = 1; i <= 5; i++) {
      var r = await call('DELETE', '/users/me',
                         payload('WrongPass' + i, CONFIRM_TEXT), tokenA);
      if (i === 1) { first = r; }
      if (i === 5) { last = r; }
    }
    ok('A-07 密码错误第 1 次 -> 422 PASSWORD_INVALID',
       first.status === 422 && codeOf(first.body) === 'PASSWORD_INVALID',
       'HTTP ' + first.status + ' ' + codeOf(first.body));
    ok('A-07 密码错误第 5 次 -> 422 PASSWORD_INVALID（**不返回 429、不锁定**）',
       last.status === 422 && codeOf(last.body) === 'PASSWORD_INVALID',
       'HTTP ' + last.status + ' ' + codeOf(last.body));
    ok('A-07 密码错误响应 data === null（失败 envelope）',
       (last.body || {}).data === null, JSON.stringify((last.body || {}).data));

    var lg = await call('POST', '/auth/login', { username: UA, password: PWD });
    ok('A-07 连续 5 次密码错误**不影响登录**（同密码仍 200）',
       lg.status === 200, 'HTTP ' + lg.status + ' ' + codeOf(lg.body));

    var lr = await call('GET', '/records?limit=100', null, tokenA);
    ok('A-07 多次密码错误后 A 端数据**未变**（活跃仍 3 条）',
       ((dataOf(lr.body).items) || []).length === 3,
       String(((dataOf(lr.body).items) || []).length));
  }

  async function group4NoEffectParams() {
    /* 对端持“范围扩展参数 + 错误密码”：force 不得绕过密码闸门，A 端不得被牵连 */
    var f = await call('DELETE', '/users/me',
                       { confirm_text: CONFIRM_TEXT, password: 'WrongPass9',
                         force: true, target_user_id: 1, grace_period: 0,
                         defer: true, schedule: 'now' }, tokenB);
    ok('A-07 对端 force=true 仍不能绕过密码闸门 -> 422 PASSWORD_INVALID',
       f.status === 422 && codeOf(f.body) === 'PASSWORD_INVALID',
       'HTTP ' + f.status + ' ' + codeOf(f.body));

    var meA = await call('GET', '/users/me', null, tokenA);
    ok('A-07 对端越权尝试**未影响** A 端账号（A 仍 200）', meA.status === 200,
       'HTTP ' + meA.status);
    var meB = await call('GET', '/users/me', null, tokenB);
    ok('A-07 对端越权尝试**未注销** B 端自身（B 仍 200）', meB.status === 200,
       'HTTP ' + meB.status);
  }

  async function group5CloseSuccess() {
    var r = await call('DELETE', '/users/me',
                       { confirm_text: CONFIRM_TEXT, password: PWD,
                         client_time: stamp(0, 12, 0),
                         target_user_id: 999999, force: true, grace_period: 30,
                         defer: true, schedule: 'later' }, tokenA);
    var d = dataOf(r.body);
    ok('A-07 成功注销 200', r.status === 200, 'HTTP ' + r.status + ' ' + codeOf(r.body));
    okEq('A-07 成功 envelope 恰 4 键', sortedKeys(r.body), ENVELOPE_KEYS);
    ok('A-07 成功 data **恰 1 键** account_closed === true',
       sortedKeys(d).join(',') === CLOSED_KEYS.join(',') && d.account_closed === true,
       sortedKeys(d).join(',') + ' / ' + JSON.stringify(d));
    ok('A-07 成功文案为「账号已注销」（与「退出登录」严格区分）',
       msgOf(r.body) === CLOSED_MESSAGE, msgOf(r.body));
    ok('A-07 成功响应**无** soft_warning / warnings / 删除条数字段',
       Object.prototype.hasOwnProperty.call(d, 'soft_warning') === false &&
       Object.prototype.hasOwnProperty.call(d, 'warnings') === false &&
       Object.prototype.hasOwnProperty.call(d, 'deleted_records') === false,
       JSON.stringify(d));
    ok('A-07 成功响应**不含** user_id / password / file_path 等敏感键',
       JSON.stringify(r.body).indexOf('user_id') < 0 &&
       JSON.stringify(r.body).indexOf('password') < 0 &&
       JSON.stringify(r.body).indexOf('file_path') < 0,
       JSON.stringify(r.body));
  }

  async function group6TokenInvalid() {
    var a1 = await call('GET', '/users/me', null, tokenA);
    ok('A-07 后旧 Access Token 访问 /users/me -> 401', a1.status === 401, 'HTTP ' + a1.status);

    var a2 = await call('GET', '/records', null, tokenA);
    ok('A-07 后旧 Access Token 访问 /records -> 401', a2.status === 401, 'HTTP ' + a2.status);

    var a3 = await call('POST', '/auth/refresh', { refresh_token: refreshA });
    ok('A-07 后旧 refresh_token -> 401（会话已物理删除）',
       a3.status === 401, 'HTTP ' + a3.status + ' ' + codeOf(a3.body));

    var a4 = await call('DELETE', '/users/me', payload(PWD, CONFIRM_TEXT), tokenA);
    ok('A-07 重复注销（旧 Token 重放）-> 401（天然幂等，不泄露账号状态）',
       a4.status === 401, 'HTTP ' + a4.status + ' ' + codeOf(a4.body));

    var lg = await call('POST', '/auth/login', { username: UA, password: PWD });
    ok('A-07 后原凭据登录 -> 401 CREDENTIALS_INVALID（账号确已不存在）',
       lg.status === 401 && codeOf(lg.body) === 'CREDENTIALS_INVALID',
       'HTTP ' + lg.status + ' ' + codeOf(lg.body));
  }

  async function group7UsernameReleased() {
    var rg = await call('POST', '/auth/register', {
      username: UA, password: PWD,
      agreement_version: 'v1.0', agreement_accepted: true
    });
    ok('A-07 后同用户名**可重新注册**（用户名已释放）',
       rg.status === 200 || rg.status === 201,
       'HTTP ' + rg.status + ' ' + codeOf(rg.body));

    var lg = await call('POST', '/auth/login', { username: UA, password: PWD });
    ok('A-07 后重新注册账号**可登录**', lg.status === 200,
       'HTTP ' + lg.status + ' ' + codeOf(lg.body));
    var newToken = (dataOf(lg.body).tokens || {}).access_token || '';
    ok('A-07 后重新注册账号拿到**新** Access Token', newToken.length > 0 &&
       newToken !== tokenA, String(newToken.length));

    var lr = await call('GET', '/records?limit=100', null, newToken);
    ok('A-07 后新账号**无任何历史记录残留**（items 为空）',
       lr.status === 200 && ((dataOf(lr.body).items) || []).length === 0,
       'HTTP ' + lr.status + ' items=' + ((dataOf(lr.body).items) || []).length);

    var pr = await call('GET', '/profile', null, newToken);
    var pd = (pr.status === 200 ? dataOf(pr.body) : {}).profile || null;
    ok('A-07 后新账号**无档案残留**（档案行整体删除：昵称/性别/出生日期亦为 null，'
       + '与 D-02 的“仅置空 6 个健康字段”严格区分）',
       pr.status === 200 && pd !== null && pd.nickname === null &&
       pd.gender === null && pd.birth_date === null && pd.blood_type === null,
       'HTTP ' + pr.status + ' / profile=' + JSON.stringify(pd));
  }

  async function group8PeerUntouched() {
    var b1 = await call('GET', '/users/me', null, tokenB);
    ok('隔离：B 端旧 Token **仍可用** -> 200', b1.status === 200,
       'HTTP ' + b1.status + ' ' + codeOf(b1.body));

    var b2 = await call('GET', '/records?limit=100', null, tokenB);
    ok('隔离：B 端记录仍**恰 1 条**（未被误删）',
       b2.status === 200 && ((dataOf(b2.body).items) || []).length === 1,
       'HTTP ' + b2.status + ' items=' + ((dataOf(b2.body).items) || []).length);

    var b3 = await call('GET', '/goals', null, tokenB);
    ok('隔离：B 端 /goals 仍可读（未被误删）', b3.status === 200, 'HTTP ' + b3.status);

    var b4 = await call('POST', '/records',
                        { metric_type: 'weight', value_1: 61,
                          recorded_at: stamp(0, 9, 0) }, tokenB);
    ok('隔离：B 端仍可正常写入（账号与数据面完全正常）', b4.status === 201,
       'HTTP ' + b4.status);
  }

  async function group9LeakScan() {
    var r = await call('DELETE', '/users/me', payload('WrongPass1', CONFIRM_TEXT), tokenB);
    var t = JSON.stringify(r.body || {});
    ok('错误响应不泄漏内部细节（无 Traceback / File " / sqlalchemy / 栈帧）',
       t.indexOf('Traceback') < 0 && t.indexOf('File "') < 0 &&
       t.indexOf('sqlalchemy') < 0 && t.indexOf('Traceback (most recent call last)') < 0, t);

    var er = errorsOf(r.body);
    ok('错误响应 envelope：4 必备键齐备 + data === null',
       ENVELOPE_KEYS.every(function (k) {
         return Object.prototype.hasOwnProperty.call(r.body || {}, k);
       }) && (r.body || {}).data === null,
       sortedKeys(r.body).join(','));

    var vf = await call('DELETE', '/users/me', { password: PWD }, tokenB);
    var ver = errorsOf(vf.body);
    ok('字段级明细仅在 VALIDATION_FAILED 出现，且每项恰 3 键（field / code / message）',
       vf.status === 422 && codeOf(vf.body) === 'VALIDATION_FAILED' && ver.length === 1 &&
       sortedKeys(ver[0]).join(',') === 'code,field,message',
       'HTTP ' + vf.status + ' ' + JSON.stringify(ver));
    ok('PASSWORD_INVALID 类错误**不带**字段级明细（errors 键缺省或为空）',
       Array.isArray(er) === false || er.length === 0,
       JSON.stringify(er));

    var hp = await call('GET', '/health');
    ok('运行时文案中性：/health 响应不含医学结论类字样',
       JSON.stringify(hp.body || {}).indexOf('诊断') < 0 &&
       JSON.stringify(hp.body || {}).indexOf('处方') < 0 &&
       JSON.stringify(hp.body || {}).indexOf('用药建议') < 0,
       JSON.stringify(hp.body || {}));
  }

  /* 收尾：**不删除 B 端账号**（浏览器端无权限），交由素材 B 第 3 段 SQL 清理；
     此处仅软删本脚本为 B 端新写入的那条记录。 */
  async function cleanup() {
    say('  收尾：A 端已由 A-07 自身注销；B 端 tstb8edgeb 请用素材 B 第 3 段 SQL 清理。');
    var lr = await call('GET', '/records?limit=100', null, tokenB);
    var items = dataOf(lr.body).items || [];
    var n = 0;
    for (var i = 0; i < items.length; i++) {
      var d = await call('DELETE', '/records/' + items[i].id, null, tokenB);
      if (d.status === 200) {
        n++;
      }
    }
    say('  收尾：B 端记录已软删 ' + n + ' 条（账号本身仍需 SQL 清理）。');
  }

  async function run() {
    say('=====================================================================');
    say('S2 第八批 A-07（注销账号）· Edge 一键验收');
    say('目标后端：' + BASE + '    账号：' + UA + ' / ' + UB);
    say('=====================================================================');

    try {
      await group0Connect();
      if (results[0].pass !== true) {
        say('  [STOP] 连通性失败，后端未就绪：cd backend && .venv/Scripts/python.exe wsgi.py');
        report();
        return;
      }

      var bA = await boot(UA);
      var bB = await boot(UB);
      tokenA = bA.access;
      refreshA = bA.refresh;
      tokenB = bB.access;
      ok('双账号就绪（tstb8edgea 主体 / tstb8edgeb 对端）',
         !!tokenA && !!tokenB && !!refreshA);
      if (!tokenA || !tokenB) {
        say('  [STOP] 账号登录失败，无法继续。');
        report();
        return;
      }

      var groups = [
        ['1. A 端 / B 端造数（3 活跃 + 1 软删 + 档案 + 2 目标）', group1Seed],
        ['2. 三重确认反向（confirm_text / password / client_time）', group2ConfirmNegative],
        ['3. 密码错误（422 PASSWORD_INVALID，无 429 / 无锁定）', group3WrongPassword],
        ['4. 范围扩展参数无效果（force 不绕过闸门）', group4NoEffectParams],
        ['5. A-07 注销成功（shape / 文案 / 敏感键）', group5CloseSuccess],
        ['6. 注销后 Token 与 refresh 全部失效', group6TokenInvalid],
        ['7. 用户名释放（可重新注册 / 无历史残留）', group7UsernameReleased],
        ['8. 对端账号与数据完全不受影响', group8PeerUntouched],
        ['9. 泄漏与错误 envelope 扫描', group9LeakScan]
      ];
      for (var i = 0; i < groups.length; i++) {
        say('');
        say('── ' + groups[i][0] + '  --------');
        try {
          await groups[i][1]();
        } catch (err) {
          ok('【' + groups[i][0] + '】块内异常', false, String(err));
        }
      }
    } catch (err) {
      ok('顶层执行异常', false, String(err));
    } finally {
      try {
        await cleanup();
      } catch (err2) {
        say('  [WARN] 收尾异常：' + String(err2));
      }
      report();
    }
  }

  function report() {
    var passed = 0;
    for (var i = 0; i < results.length; i++) {
      if (results[i].pass) {
        passed++;
      }
    }
    say('');
    say('=====================================================================');
    say('  合计 ' + passed + '/' + results.length + ' 通过，' + (results.length - passed) + ' 项失败');
    say('  结论：' + (passed === results.length ? '全部通过' : '存在失败项'));
    if (results.length - passed > 0) {
      say('  失败项：');
      for (var j = 0; j < fails.length; j++) {
        say('    - ' + fails[j]);
      }
    }
    say('  提醒：A-07 只对本脚本自建测试账号执行；请执行素材 B 第 3 段 SQL 清理');
    say('        tstb8edgea / tstb8edgeb 两个测试账号及其业务数据。');
    say('=====================================================================');
  }

  run();
})();
