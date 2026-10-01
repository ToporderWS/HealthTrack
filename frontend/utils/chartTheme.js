/**
 * 图表主题与数据适配层（S3-4 / SC-11 趋势页 · C-23 `TrendChartContainer` 专用）
 *
 * 职责边界（**只做适配，不做业务判断**）：
 *   ① 把 DESIGN.md 的**运行时令牌**（`App.vue` 的 `--x`）读成 canvas 可用的具体色值；
 *   ② 把 S-02 的 `points[]` 适配成 uCharts 的 `{ categories, series }`；
 *   ③ 把 S-02/S-03 的字段口径（含睡眠的单位修正）集中在一处，避免页面与组件各写一套。
 *
 * ★ 为什么需要「读令牌」而不是在 JS 里写色值（DESIGN.md §1.2 / §9 硬规则）：
 *   DESIGN.md §9 明确「不得直接写 HEX」，§1.2 规定运行时**唯一真相源**是 `App.vue` 上的 `--x`。
 *   canvas 无法消费 `var(--x)`，故此处以 `getComputedStyle` 从 `:root` / `page` 读取**同名令牌**，
 *   既不复制字面值，也不新增第 9 个图表颜色。读取失败时返回空串，
 *   由调用方回退到库默认值（**不伪造颜色**），并在页面状态上如实体现。
 *
 * ★★ App 端为什么还需要「视图层快照」（S3-9 3.3 第4步 实测结论，勿删）：
 *   `getComputedStyle` 只存在于 **H5 的浏览器环境**；App（app-plus / vue3）的**逻辑层没有 DOM**
 *   ⇒ `readToken()` 在真机上一律返回空串，`chartTokens().ok` 恒为 false。
 *   此时 uCharts 拿到的是 `color: ['']`、`axisLineColor: ''`、`gridColor: ''`、`background: ''`，
 *   而 **canvas 对空串赋值是 no-op**（保持上一个成功设定的值）⇒ 实测真机表现为：
 *     柱体填充 = `#666666`（残留自轴文字色）、折线描边 = `#cccccc`（残留自网格色）、
 *     轴文字 = `#666666`（库默认，而非 `--t-3`）
 *   —— 这才是「整图偏深灰、与康迹青体系不统一」的真因（**不是配色选错，也不是令牌未注册**：
 *   实测 `app.css` 里 `--c-chart-main: #0E9384` 一直在，只是逻辑层读不到）。
 *   ⇒ 修复通道：组件用 **renderjs** 在**视图层**（有真实 DOM 与 app.css）枚举 CSS 自定义属性，
 *     经 `$ownerInstance.callMethod` 回传逻辑层；本模块的 `readToken(name, snapshot)` 用它兜底。
 *   ★ 取值优先级固定为「**DOM 直读优先、快照兜底**」⇒ H5 的取值来源与绘制次数与改动前一致。
 *
 * ★ 数据诚实性（DESIGN.md §9 / S1-C SC-11 ④，逐条落实）：
 *   ① 缺失日期 → `null`（**不补 0、不插值**）⇒ 配合 `connectNulls: false` 折线真实断开；
 *   ② 柱状图缺日同样为 `null` ⇒ **不画零高柱**；
 *   ③ 睡眠按后端 `recorded_at`（起床时间）归属起床日 —— **客户端不重算归属**，直接用服务端 `date`；
 *   ④ 窗口由**服务端**计算（`window.start` / `window.end` / `window.days`）—— 客户端只按该区间铺类别轴；
 *   ⑤ 90 天用服务端聚合点，**不做客户端抽样**（只限制 X 轴**标签**密度，不丢弃任何数据点）。
 */

import { metricUnit } from './metrics'
import { pad2 } from './validate'

/* ════════════════════════════════════════════════════════════════════
 * ① 令牌桥（DESIGN.md §2.5 / §2.1 / §3；**只写令牌名，不写字面色值**）
 * ════════════════════════════════════════════════════════════════════ */

/** 图表适配用到的令牌名（与 `App.vue` 的 `--x` 逐字一致） */
export const CHART_TOKEN = {
    /** 单折线 / 柱体主色（8 类指标共用，§2.5） */
    main: '--c-chart-main',
    /** 双线主线（血压-收缩压，§2.5） */
    a: '--c-chart-a',
    /** 双线副线（血压-舒张压，§2.5） */
    b: '--c-chart-b',
    /** 用户目标线（虚线，§2.5） */
    goal: '--c-chart-goal',
    /** 横网格线（§2.5） */
    grid: '--c-chart-grid',
    /** 坐标轴文字 = `--t-3`（§2.5③） */
    axisText: '--t-3',
    /** 气泡底色 = 中性阶最深档（§2.1 `--c-n-800`） */
    bubbleBg: '--c-n-800',
    /** 气泡文字 = 反白文字（§2.4 `--t-inverse` = `--c-n-0`） */
    bubbleText: '--c-n-0',
    /** 图表底色 = 卡片底（§2.4 `--s-card` = `--c-n-0`） */
    surface: '--c-n-0',
    /** 坐标轴字号 = `--fs-caption`（§2.5③ / §3） */
    fsCaption: '--fs-caption'
}

/** 令牌读取缓存（一次会话内只需读一次；`resetChartTokens()` 可强制重读） */
/* ★ 缓存键含「快照对象引用」：App 端快照到达后必须重算，故以引用变化作为失效条件 */
const tokenCache = { done: false, values: null, ok: false, snapshot: null }

/** 从单个元素的 computedStyle 读一个自定义属性；不可用 / 未定义 → 空串 */
function readFrom(el, name) {
    if (!el || typeof window === 'undefined' || typeof window.getComputedStyle !== 'function') {
        return ''
    }
    try {
        const value = window.getComputedStyle(el).getPropertyValue(name)
        return value ? String(value).trim() : ''
    } catch (e) {
        return ''
    }
}

/**
 * 读取一个令牌的运行时值。
 *
 * 取值链（按 DESIGN.md §10.1 页面骨架：`:root` 与 `page` 上都注册了同名令牌）：
 *   ① DOM 直读（H5）：`documentElement`（`:root`）→ `body` → `uni-page-body`（H5 的 `page` 落点）；
 *   ② **视图层快照兜底**（App 端唯一通道，见文件头 ★★）。
 * 首个非空值即返回；全部为空 → 空串（**不编造色值**）。
 *
 * @param {string} name 令牌名（形如 `--c-chart-main`）
 * @param {object} [snapshot] 视图层回传的「令牌名 → 运行时值」表；H5 传 null 即走纯 DOM 链
 * @returns {string} 令牌的运行时原文（未解析相对单位）；取不到 → 空串
 */
export function readToken(name, snapshot) {
    if (typeof document === 'undefined') {
        return snapshotValue(snapshot, name)
    }
    const sources = []
    if (document.documentElement) {
        sources.push(document.documentElement)
    }
    if (document.body) {
        sources.push(document.body)
    }
    if (typeof document.querySelector === 'function') {
        try {
            const pageBody = document.querySelector('uni-page-body')
            if (pageBody) {
                sources.push(pageBody)
            }
        } catch (e) {
            // 忽略：查询失败不影响主链路
        }
    }
    for (let i = 0; i < sources.length; i++) {
        const value = readFrom(sources[i], name)
        if (value) {
            return value
        }
    }
    return snapshotValue(snapshot, name)
}

/**
 * 从**视图层快照**取一个令牌值（App 端兜底；H5 传入 null 时恒为空串）。
 * @returns {string} 空串 = 无快照 / 该令牌未命中（调用方沿用库默认，**不伪造颜色**）
 */
function snapshotValue(snapshot, name) {
    if (!snapshot || !name) {
        return ''
    }
    const value = snapshot[name]
    return value ? String(value).trim() : ''
}

/** 当前窗口宽度（`px`）；取不到 → 0（调用方据此跳过 rpx 换算，不猜测屏幕尺寸） */
function windowWidth() {
    try {
        if (typeof uni !== 'undefined' && typeof uni.getWindowInfo === 'function') {
            const info = uni.getWindowInfo()
            if (info && info.windowWidth) {
                return Number(info.windowWidth)
            }
        }
    } catch (e) {
        // 落到下面的兜底
    }
    try {
        if (typeof uni !== 'undefined' && typeof uni.getSystemInfoSync === 'function') {
            const info = uni.getSystemInfoSync()
            if (info && info.windowWidth) {
                return Number(info.windowWidth)
            }
        }
    } catch (e) {
        // 取不到就返回 0
    }
    return 0
}

/**
 * 用浏览器自己的 CSS 解析器把**带相对单位**的长度换算成 px。
 *
 * ★ 为什么必须有它（踩坑记录，勿删）：
 *   `getComputedStyle().getPropertyValue('--x')` 返回的是**未解析的原文**，
 *   而本工程的字号令牌经 H5 构建后运行时是相对单位 —— `--fs-caption` 的实际值是
 *   `0.75rem`（`uni.scss` 里写的是 `24rpx`，构建期按 750 基准转成 rem）。
 *   早期实现只认 `rpx`，遇到 `rem` 会落进 `Math.round(0.75)` ⇒ **1**
 *   ⇒ X 轴日期被画成 1px（肉眼只剩几条小短横，DESIGN.md §9 的「逐日日期」形同不展示）。
 *   这里把令牌值挂到一个**隐藏探针元素**的 `fontSize` 上，再读 `getComputedStyle` ——
 *   浏览器返回的一定是**解析后的绝对 px**，与页面真实渲染同源；
 *   既不写死 `16px`，也不新增依赖。
 *
 *   ★ 为什么不用 canvas 的 `font` 简写（已实测踩过，勿改回）：
 *     Chrome 里 `ctx.font` 对 `rem` 的解析基准与**文档根字号不一致**
 *     （实测把 `0.75rem` 解成 16px，而页面真实渲染约 12px）⇒ 会引入静默误差。
 *
 * @returns {number} px；0 = 无法解析（调用方沿用库默认，**绝不猜测**）
 */
function browserLengthToPx(raw) {
    if (typeof document === 'undefined' || typeof document.createElement !== 'function' || !document.body) {
        return 0
    }
    try {
        const probe = document.createElement('div')
        probe.style.position = 'absolute'
        probe.style.visibility = 'hidden'
        probe.style.pointerEvents = 'none'
        probe.style.fontSize = raw
        // 浏览器不接受的值会被丢弃 ⇒ 借这一点自校验，不猜测
        if (!probe.style.fontSize) {
            return 0
        }
        document.body.appendChild(probe)
        const computed = typeof window !== 'undefined' && window.getComputedStyle
            ? window.getComputedStyle(probe).fontSize
            : ''
        document.body.removeChild(probe)
        const m = /(\d+(?:\.\d+)?)px/.exec(String(computed || ''))
        if (!m) {
            return 0
        }
        const px = parseFloat(m[1])
        return px > 0 ? Math.round(px) : 0
    } catch (e) {
        return 0
    }
}

/**
 * CSS 长度字符串 → `px` 数值。
 * - `rpx`：按 750 设计稿基准换算（DESIGN.md §10.4①），首选运行时窗口宽度；
 * - `px` / 裸数字：原样取整；
 * - 其余（`rem` / `em` / …）：交给浏览器解析（见 `browserLengthToPx`）。
 * 参数非法、取不到窗口宽度、或无法解析 → `0`（调用方沿用库默认）。
 */
function cssLengthToPx(text) {
    const raw = String(text == null ? '' : text).trim()
    if (!raw) {
        return 0
    }
    const num = parseFloat(raw)
    if (isNaN(num) || num <= 0) {
        return 0
    }
    if (/rpx$/i.test(raw)) {
        const width = windowWidth()
        if (!width) {
            return 0
        }
        return Math.round(num * width / 750)
    }
    if (/px$/i.test(raw) || /^\d+(\.\d+)?$/.test(raw)) {
        return Math.round(num)
    }
    return browserLengthToPx(raw)
}

/**
 * 读取全部图表令牌。
 *
 * ★ `snapshot` 参与缓存键：传入的**对象引用**与上次不同即重算。
 *   App 端首次调用（快照未到）会得到 `ok = false`；快照回传后再调用即拿到真值。
 * @param {object} [snapshot] 视图层回传的令牌表（H5 传 null）
 * @returns {{values: object, ok: boolean}} `ok = false` 表示有令牌缺失（调用方需降级）
 */
export function chartTokens(snapshot) {
    if (!tokenCache.done || tokenCache.snapshot !== snapshot) {
        const values = {}
        let ok = true
        for (const key in CHART_TOKEN) {
            if (Object.prototype.hasOwnProperty.call(CHART_TOKEN, key)) {
                const value = readToken(CHART_TOKEN[key], snapshot)
                values[key] = value
                if (!value) {
                    ok = false
                }
            }
        }
        tokenCache.values = values
        tokenCache.ok = ok
        tokenCache.done = true
        tokenCache.snapshot = snapshot
    }
    return { values: tokenCache.values, ok: tokenCache.ok }
}

/** 丢弃令牌缓存（主题变化 / 需要在其它时机强制重读时调用） */
export function resetChartTokens() {
    tokenCache.done = false
    tokenCache.values = null
    tokenCache.ok = false
    tokenCache.snapshot = null
}

/**
 * `--fs-caption` 的 **px** 数值（uCharts 的 `fontSize` 只接受数字，不吃 CSS 变量）。
 *
 * 依据 DESIGN.md §2.5③「坐标轴文字取 `--fs-caption`」/ §3：canvas 侧只能接收数字，
 * 故此处把令牌的**运行时值**换算为 px。
 * ★ 注意：令牌在 `uni.scss` 里以 `rpx` 书写，但经 H5 构建后运行时读到的是**相对单位**
 *   （实测 `--fs-caption` = `0.75rem`）⇒ 必须走 `cssLengthToPx` 让浏览器解析，
 *   不能只做 `parseFloat`（那会把 `0.75` 取整成 `1`）。
 * 取不到令牌 / 无法解析 → `0`（调用方**沿用库默认字号**，不猜测屏幕尺寸）。
 *
 * ★ App 端说明（S3-9 3.3 第4步）：即便快照已带回 `--fs-caption`（实测运行时值 `0.75rem`），
 *   逻辑层**没有浏览器**可把它解析成 px ⇒ 真机仍返回 0 ⇒ X 轴沿用库默认字号。
 *   这**正是真机已验收过的行为**，本轮**刻意不改**（改它等于动已通过的 X 轴修复）。
 *
 * @returns {number} px；0 表示"无可用值，请沿用库默认"
 */
export function captionFontPx(snapshot) {
    const raw = readToken(CHART_TOKEN.fsCaption, snapshot)
    if (!raw) {
        return 0
    }
    return cssLengthToPx(raw)
}

/* ════════════════════════════════════════════════════════════════════
 * ② 类型 / 字段 / 系列名（全部来自后端冻结契约，客户端不另立一套）
 * ════════════════════════════════════════════════════════════════════ */

/**
 * S-02 `chart` 字段（`'line'` / `'bar'`）→ uCharts 组件 `type`。
 * 依据：后端 `stats_service.CHART`（weight/bp/heart/glucose/mood = line；sleep/water/sport = bar）。
 * uCharts 的柱状类型名是 `column`，故 `bar → column`。
 */
export function uchartsType(apiChart) {
    return apiChart === 'bar' ? 'column' : 'line'
}

/**
 * 每个指标在 `points[]` 里被绘制的字段（依据后端 `_trend_points`，逐类对照）。
 * - `weight` → `value`（当日最后一次）
 * - `bp`     → `systolic` + `diastolic`（当日均值）
 * - `heart` / `glucose` / `mood` → `value`（当日均值）
 * - `sleep`  → `duration_hours`（当日累计小时）
 * - `water`  → `total_ml`（当日累计）
 * - `sport`  → `minutes`（当日累计）
 */
export const POINT_FIELDS = {
    weight: ['value'],
    bp: ['systolic', 'diastolic'],
    heart: ['value'],
    glucose: ['value'],
    sleep: ['duration_hours'],
    water: ['total_ml'],
    sport: ['minutes'],
    mood: ['value']
}

/** 系列展示名（只陈述「画的是什么」，不含任何医学判断，DESIGN.md §12） */
export const SERIES_NAME = {
    weight: ['体重'],
    bp: ['收缩压', '舒张压'],
    heart: ['心率'],
    glucose: ['血糖'],
    sleep: ['睡眠时长'],
    water: ['饮水'],
    sport: ['运动时长'],
    mood: ['心情']
}

/**
 * 图表与摘要的**数值单位**。
 *
 * ★ 口径说明（如实登记，**不改后端**）：
 *   S-02 / S-03 的 `unit` 取自后端 `metric_rules.METRIC_UNIT`，其中 `sleep = 'score'`；
 *   但睡眠在趋势与摘要中输出的数值字段是 `duration_hours` / `average_duration_hours`（**小时**）。
 *   若直接展示接口的 `unit`，会出现「时长数值 + score 单位」的错误配对，
 *   故本页对 `sleep` 使用「小时」，其余 7 类一律以接口下发的 `unit` 为准。
 */
export const SLEEP_DURATION_UNIT = '小时'

/** @returns {string} 展示用单位 */
export function chartUnit(metricType, unitFromApi) {
    if (metricType === 'sleep') {
        return SLEEP_DURATION_UNIT
    }
    return metricUnit(metricType, unitFromApi)
}

/**
 * X 轴**标签**数量 → uCharts `opts.xAxis.labelCount`
 * （DESIGN.md §9：7 天逐日 / 30 天每 5 天 / 90 天每 15 天）。
 *
 * ★ 为什么是 8 / 7 / 7，而不是 7 / 6 / 6（踩坑记录，勿改回）：
 *   uCharts `drawXAxis()` 的抽稀算法是（未设 `xAxis.itemCount` 时）：
 *     maxXAxisListLength = opts.xAxis.labelCount;
 *     maxXAxisListLength -= 1;                                   // ★ 库自己先减 1
 *     ratio = Math.ceil(categories.length / maxXAxisListLength);
 *     if (i % ratio !== 0) → 该位标签置空；末位强制显示
 *   ⇒ **实际显示数量 = labelCount - 1**。
 *   代入 DESIGN.md §9 的目标密度：
 *     - 7 天逐日（要 7 个）⇒ labelCount = 8 ⇒ ratio = ceil(7 / 7) = 1 ⇒ 7 个全显；
 *     - 30 天每 5 天（ratio = 5 ⇒ 0,5,10,15,20,25）⇒ labelCount = 7 ⇒ ratio = ceil(30 / 6) = 5；
 *     - 90 天每 15 天（ratio = 15 ⇒ 0,15,30,45,60,75）⇒ labelCount = 7 ⇒ ratio = ceil(90 / 6) = 15。
 *   旧值 7 / 6 / 6 会让 7 天窗口得到 ratio = ceil(7 / 6) = 2 ⇒ **只显示 4 个日期**
 *   （实测正是 4 个：09-11 / 09-13 / 09-15 …，与 §9「逐日」不符）。
 *
 * 注意：这里只影响标签**显示密度**，**不抽样、不丢弃数据点**（数据诚实性 ⑤）。
 * @returns {number} 0 表示不限制（沿用库默认）
 */
export function labelCountOf(days) {
    const n = Number(days)
    if (n === 7) {
        return 8
    }
    if (n === 30) {
        return 7
    }
    if (n === 90) {
        return 7
    }
    return 0
}

/** 设计密度对应的**类别步长**（DESIGN.md §9：7 天逐日 / 30 天每 5 天 / 90 天每 15 天） */
function designStep(days) {
    const n = Number(days)
    if (n === 7) {
        return 1
    }
    if (n === 30) {
        return 5
    }
    if (n === 90) {
        return 15
    }
    return 0
}

/**
 * X 轴 `labelCount`：**先按 DESIGN.md §9 的设计密度，放不下才降档**。
 *
 * ★ 为什么需要它（S3-9 3.3 第3步 · 真机视觉适配）：
 *   库的抽稀只看 `labelCount`，**从不检查标签会不会互相压叠**；而 `eachSpacing`
 *   与字号完全解耦（见 `shortDayLabel` 的说明）⇒ 只要运行环境把字号放大，
 *   设计密度就会画成一片糊字。真机已实测到该现象。
 *   ⇒ 这里按"实测标签宽 vs 保守绘图区宽"求能放下的个数，**只在放不下时**把
 *   步长按设计步长的整数倍放大（1→2→3…／5→10…／15→30…），能放下就原样返回设计值。
 *
 * ★ 三种"测不到"一律回落到 `labelCountOf(days)`（= 与改动前**逐字节相同**的行为）：
 *   窗口宽度不可得、`--gutter` 不可解析、`--fs-caption` 解析不出 px。
 *   宁可维持原样，也不猜测屏幕与字号。
 *
 * ★ 不变量：**只影响标签显示密度，不抽样、不丢弃任何数据点**（数据诚实性 ⑤）。
 *   例：7 天窗口 `step=1` ⇒ `ceil(7/1)+1 = 8`（与旧值一致，7 个标签全显）。
 *
 * @param {number} days 服务端窗口天数
 * ★ App 端说明（S3-9 3.3 第4步）：真机 `captionPx` 恒为 0（见 `captionFontPx`）
 *   ⇒ 本函数在真机上会在上面第一道回落处直接返回**设计密度**（8 / 7 / 7），即真机不参与降档。
 *   （若日后要让真机也降档，需把视图层快照一并传入本函数与 `plotWidthEstimate`；
 *   本轮**不做**，避免改动已验收的 X 轴行为。）
 *
 * @param {number} captionPx `--fs-caption` 的 px（0 = 不可得）
 * @param {object} payload S-02 的 `data`（取 `window` 复原标签文本样例）
 * @returns {number} 0 = 不限制（沿用库默认）
 */
export function labelCountForFit(days, captionPx, payload) {
    const n = Number(days)
    const step = designStep(n)
    const designed = labelCountOf(n)
    if (!n || !step || !designed || !captionPx) {
        return designed
    }
    const plot = plotWidthEstimate()
    if (!plot) {
        return designed
    }
    /* 用**本窗口真实日期**做样例（去前导零后最长者），逐条量宽取最大值 */
    const days_ = windowCategories(payload && payload.window)
    let labelW = 0
    for (let i = 0; i < days_.length; i++) {
        const wpx = measureTextPx(shortDayLabel(days_[i]), captionPx)
        if (wpx > labelW) {
            labelW = wpx
        }
    }
    if (!labelW) {
        return designed
    }
    /** 相邻标签最小净间隙（CSS px）：低于它即视为"读不出来"，宁可少画几个 */
    const MIN_GAP = 4
    const fit = Math.max(1, Math.floor((plot + MIN_GAP) / (labelW + MIN_GAP)))
    /* 设计密度下的实际显示数 = floor((n-1)/ratio)+1，ratio 即设计步长 */
    let ratio = step
    while (floorLabelCount(n, ratio) > fit && ratio < n) {
        ratio += step
    }
    if (ratio === step) {
        return designed
    }
    return Math.min(designed, Math.ceil(n / ratio) + 1)
}

/** 给定抽稀比时 uCharts 实际会画出的标签个数（`i % ratio === 0` 的位置） */
function floorLabelCount(n, ratio) {
    return Math.floor((n - 1) / ratio) + 1
}

/* ════════════════════════════════════════════════════════════════════
 * ③ 窗口 → 类别轴 → 系列（数据诚实性均在此落实）
 * ════════════════════════════════════════════════════════════════════ */

const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})/

/** `YYYY-MM-DD...` → 本地零点 Date；不合法 → null（只做字符串裁剪，不做时区换算，S1-D D-4） */
function parseDay(text) {
    const m = DAY_RE.exec(String(text || ''))
    if (!m) {
        return null
    }
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    return isNaN(d.getTime()) ? null : d
}

/** Date → `YYYY-MM-DD` */
function fmtDay(d) {
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
}

/**
 * X 轴日期标签文本：`YYYY-MM-DD` → `M-D`（省年份、去月份前导零）。
 *
 * ★ 为什么去前导零（S3-9 3.3 第3步 · 真机视觉适配，**勿改回**）：
 *   真机尺寸实测（375×812 @dpr3、`--fs-caption` = 12px）X 轴 7 天时相邻标签
 *   **净间隙只有 8~13 CSS px**（最紧的血压 8.0）。而 uCharts 的标签间距
 *   `eachSpacing = (width - area[1] - area[3]) / categories.length`（见 u-charts.js
 *   `getXAxisPoints`）**完全由宽度决定、与字号无关**；一旦运行环境把 rem 基准放大
 *   （Android WebView 的系统「字体大小」会同时抬高 `--fs-caption` 的解析值与
 *   同以 rem 书写的边距），标签变宽而间距不增 ⇒ 立刻压叠，
 *   真机现象正是「09-1309-1409-15…」连成一片。
 *   去掉月份前导零后标签由 5 字符降为 4~5 字符，实测宽度约 −20%，把余量还给间距。
 *
 * DESIGN.md §9 只规定标签的**密度**（7 天逐日 / 30 天每 5 天 / 90 天每 15 天），
 * 未规定**格式**；窗口最长 90 天、年份冗余 ⇒ 省年份本身不损失信息。
 * ★ 缩短标签**无副作用**：uCharts `drawToolTip` 默认 `showCategory: false`，
 * 本工程未开启顶部类别名 ⇒ 点选气泡里不含日期。
 * （旧注释所称「气泡标题同样取 categories ⇒ 也会显示 MM-DD」经实测**不成立**，已更正。）
 *
 * @param {string} day `YYYY-MM-DD...`
 * @returns {string} `M-D`（如 `9-13`；非法输入原样返回）
 */
function shortDayLabel(day) {
    const s = String(day == null ? '' : day)
    if (s.length < 10) {
        return s
    }
    const md = s.slice(5)
    return md.charAt(0) === '0' ? md.slice(1) : md
}

/* ── X 轴标签"放得下与否"的度量工具（仅用于决定标签密度，不改任何数据） ── */

/** 布局令牌：页面唯一水平边距来源（与 `App.vue` 的 `--gutter` 同名） */
const LAYOUT_GUTTER = '--gutter'

/**
 * 绘图区可用宽度（CSS px）——**保守估计**，只用于判断"能放下几个标签"。
 *
 * ★ 标定来源（勿凭直觉改数）：真机尺寸（375×812 @dpr3）实测
 *   画布 CSS 宽 = 341，而 uCharts 实际使用的绘图区
 *   `width - area[1] - area[3]` ≈ **278**（由 `--fs-caption`/字号与 X 轴标签几何反推，
 *   5 个指标交叉核对，取其中最小值）⇒ 卡片宽 − 63。
 *   需要的是"放不下就别硬放"，故**宁可低估**：低估只会让标签更疏，不会压叠。
 * @returns {number} px；0 = 窗口宽度/令牌不可得（调用方沿用设计密度，**不猜测**）
 */
function plotWidthEstimate() {
    const win = windowWidth()
    if (!win) {
        return 0
    }
    const gRaw = readToken(LAYOUT_GUTTER)
    const gutter = gRaw ? cssLengthToPx(gRaw) : 0
    const cardW = gutter ? (win - 2 * gutter - 2) : (win - 34)
    const plot = cardW - 63
    return plot > 0 ? plot : 0
}

/** 文本测量上下文（一次会话内复用；取不到 → null，调用方不猜测宽度） */
let textCtx = null

/**
 * 按 uCharts 的**同一口径**量一段文本的宽度（CSS px）。
 *
 * ★ 必须与库同源：u-charts.js 的 `measureText()` 只做
 *   `context.setFontSize(fontSize)` + `context.measureText(text).width`，
 *   而 `setFontSize` 写的是 `font = fontSize + 'px sans-serif'`（实测字体串即
 *   `"36px sans-serif"`，无自定义字体族）⇒ 这里逐字复刻，不引入新字体假设。
 * ★ `measureText` 不受 dpr 影响 ⇒ 以 CSS 字号测量即得 CSS 宽度，与 `eachSpacing` 同尺度。
 */
function measureTextPx(text, fontPx) {
    if (!text || !fontPx) {
        return 0
    }
    if (typeof document === 'undefined' || typeof document.createElement !== 'function') {
        return 0
    }
    try {
        if (!textCtx) {
            const cv = document.createElement('canvas')
            textCtx = cv && typeof cv.getContext === 'function' ? cv.getContext('2d') : null
        }
        if (!textCtx) {
            return 0
        }
        textCtx.font = fontPx + 'px sans-serif'
        const width = Number(textCtx.measureText(String(text)).width)
        return width > 0 ? width : 0
    } catch (e) {
        return 0
    }
}

/** 设备像素比（柱状圆角等 canvas 尺寸需要它；取不到 → 0，调用方放弃该视觉项） */
function pixelRatio() {
    try {
        if (typeof uni !== 'undefined' && typeof uni.getWindowInfo === 'function') {
            const info = uni.getWindowInfo()
            if (info && info.pixelRatio) {
                return Number(info.pixelRatio)
            }
        }
    } catch (e) {
        // 落到下面的兜底
    }
    try {
        if (typeof window !== 'undefined' && window.devicePixelRatio) {
            return Number(window.devicePixelRatio)
        }
    } catch (e) {
        // 取不到就返回 0
    }
    return 0
}

/**
 * 按**服务端**窗口铺日期轴（含首尾）。
 * 上限 400 天为安全阀（服务端窗口最大 90 天，正常不会触及）。
 * @returns {string[]} 形如 `['2026-09-09', ...]`
 */
export function windowCategories(win) {
    const start = parseDay(win && win.start)
    const end = parseDay(win && win.end)
    if (!start || !end || start.getTime() > end.getTime()) {
        return []
    }
    const out = []
    const cursor = new Date(start.getTime())
    for (let i = 0; i < 400 && cursor.getTime() <= end.getTime(); i++) {
        out.push(fmtDay(cursor))
        cursor.setDate(cursor.getDate() + 1)
    }
    return out
}

/** 数值归一：`null` / `undefined` / `''` / 非数字 → `null`（**绝不折算成 0**） */
function toNumber(raw) {
    if (raw === null || raw === undefined || raw === '') {
        return null
    }
    const n = Number(raw)
    return isNaN(n) ? null : n
}

/**
 * S-02 载荷 → uCharts `chartData`。
 *
 * ★ 缺失日期一律填 `null`：折线在 `connectNulls: false` 下真实断开；
 *   柱状图遇 `null` 不绘制 ⇒ 不产生零高柱（DESIGN.md §9①②）。
 *
 * @param {string} metricType 8 类指标之一
 * @param {object} payload    S-02 的 `data`（含 `points` / `window` / `chart`）
 * @param {string[]} palette  按序取用的系列色（单线 1 个 / 血压 2 个）
 * @returns {{categories: string[], series: object[]}}
 */
export function buildChartData(metricType, payload, palette) {
    const colors = palette && palette.length ? palette : ['']
    const points = (payload && payload.points) || []
    const fields = POINT_FIELDS[metricType] || POINT_FIELDS.weight
    const names = SERIES_NAME[metricType] || SERIES_NAME.weight

    let categories = windowCategories(payload && payload.window)
    if (!categories.length) {
        // 兜底：窗口字段缺失时退化为「有记录的日期」（仍不造假日期）
        categories = points.map(function (p) {
            return String((p && p.date) || '')
        }).filter(function (d) {
            return !!d
        })
    }

    const byDate = {}
    for (let i = 0; i < points.length; i++) {
        const p = points[i]
        if (p && p.date) {
            byDate[String(p.date)] = p
        }
    }

    const series = []
    for (let i = 0; i < fields.length; i++) {
        const field = fields[i]
        const data = []
        for (let j = 0; j < categories.length; j++) {
            const point = byDate[categories[j]]
            data.push(point ? toNumber(point[field]) : null)
        }
        series.push({
            name: names[i] || names[0],
            data: data,
            color: colors[i] || colors[0],
            /** DESIGN.md §9①：缺失不连线，折线真实断开 */
            connectNulls: false
        })
    }
    /*
     * ★ X 轴类目**标签**只保留 `M-D`（上面所有数据映射仍用完整日期，不受影响）。
     *
     *   为什么不在 `opts.xAxis.formatter` 里做：`qiun-data-charts` 组件对 opts 执行了
     *   `JSON.parse(JSON.stringify(this.opts))` ⇒ **函数会被丢弃**，formatter 形同不存在
     *   （已实测）。库的"formatter 名字 + 注册表"机制要求改第三方 `config-ucharts.js`，
     *   本工程不改第三方源码。⇒ 只能对 categories 本身做映射（见 `shortDayLabel`）。
     */
    const axisCategories = categories.map(shortDayLabel)
    return { categories: axisCategories, series: series }
}

/**
 * S-02 载荷 → uCharts `opts`（**部分覆盖**；未给出的键沿用 `config-ucharts.js` 的模板）。
 *
 * 覆盖项与依据：
 *   - `color`：覆盖库的**彩虹**默认调色板（DESIGN.md §9「一律使用 §2.5 的 Token、不存在第 9 个颜色」）；
 *   - `dataLabel: false`：数据标签**不常驻**（§9）；
 *   - `xAxis.disableGrid`：**不画竖网格**（§9）；`xAxis.fontColor` = `--t-3`、`xAxis.fontSize` = `--fs-caption`；
 *     `xAxis.labelCount`：7 天逐日 / 30 天每 5 天 / 90 天每 15 天
 *     （★ 库的显示数量 = `labelCount - 1`，故取 8 / 7 / 7，见 `labelCountOf` 的算法说明）；
 *     `xAxis.axisLineColor` = `--c-chart-grid`：X 轴轴线同色化，消除库默认的 `#cccccc` 灰线；
 *   - `yAxis.gridType: 'dash'`：**横网格虚线**；`gridColor` = `--c-chart-grid`；`splitNumber: 4`（Y 轴 4 格 = 5 条线）；
 *   - `yAxis.data[0].fontColor` = `--t-3` / `.fontSize` = `--fs-caption`：
 *     Y 轴文字样式**必须写进 `data[0]`**（写 `yAxis` 顶层是死键，且会让预留宽度被按错误字号测量而裁掉 3 位数标签）；
 *     柱状额外带 `min: 0`（§9「柱状图必须从 0 起」），折线不设 min/max（§9「连续量可不从 0 起」）；
 *   - `legend.show`：单线**不显示图例**（§9）；血压双线显示（用于区分收缩压 / 舒张压）；
 *   - `legend.fontColor` = `--t-3`：图例文字与坐标轴文字统一（§2.5③ 同源口径）；系列色块仍取系列色，不动；
 *   - `extra.tooltip`：**气泡样式**（底 `--c-n-800` / 字 `--c-n-0`，§2.5）+ 自带 `legendShape: 'auto'`；
 *     ★ 必须写在这里，**绝不能**写 `opts.tooltip` —— 后者是 uCharts 的**运行期交互状态槽**
 *       （仅 `showToolTip()` 赋值 `{textList,offset,index,group}`），未交互时须保持 `undefined`；
 *       写了部分对象会让折线/面积整块**半渲染**（详见 `buildChartOpts` 内的警告注释）。
 *   - `extra.markLine`：目标线（仅 weight / water 有 `target_line`，§2.5 `--c-chart-goal` 虚线）；
 *   - 柱状 `yAxis.data[0].min = 0` 由本模块**显式**给出（§9「柱状必须从 0 起」）——
 *     因为显式声明 `yAxis.data` 会替换掉模板自带的 `[{min:0}]`；折线不设 min/max（§9「连续量可不从 0 起」）。
 *
 * @param {string} metricType
 * @param {object} payload S-02 的 `data`
 * @param {object} tokens  `chartTokens().values`
 * @param {number} captionPx `--fs-caption` 换算出的 px（0 = 沿用库默认）
 */
export function buildChartOpts(metricType, payload, tokens, captionPx) {
    const chartType = uchartsType(payload && payload.chart)
    const fields = POINT_FIELDS[metricType] || POINT_FIELDS.weight
    const dual = fields.length > 1
    const days = payload && payload.window ? payload.window.days : 0

    const seriesColors = dual ? [tokens.a, tokens.b] : [tokens.main]
    const opts = {
        type: chartType,
        color: seriesColors,
        background: tokens.surface,
        dataLabel: false,
        xAxis: {
            disableGrid: true,
            /*
             * ★ 必须显式给 `axisLineColor`（踩坑记录，勿删）：
             *   `disableGrid: true` 只关掉**竖网格**；X 轴**轴线**由 `axisLine` 单独控制，
             *   库默认 `axisLine: true` + `axisLineColor: '#cccccc'`（u-charts.js 默认值区），
             *   于是这条 1px 实心全宽灰线**一直画在图上**，与同样是灰色的 Y 轴轴线
             *   一起构成"图表发灰"的主因（实测 7 天 833 次 / 90 天 5206 次 `#cccccc` 描边）。
             *   这里让它与横网格同色（`--c-chart-grid`）⇒ 全图不再出现调色板外的灰。
             */
            axisLineColor: tokens.grid,
            fontColor: tokens.axisText
            /*
             * ★ 这里**不能**用 `xAxis.formatter` 改标签格式（踩坑记录，勿加）：
             *   `qiun-data-charts` 组件对 opts 执行了 `JSON.parse(JSON.stringify(this.opts))`
             *   ⇒ **函数会被丢弃**（实测设了完全不生效）。库的替代机制是
             *   "formatter 名字 + 注册表"，但注册表在第三方文件 `config-ucharts.js` 里，
             *   本工程不改第三方源码。
             *   ⇒ 标签格式在 `buildChartData()` 里对 categories 处理（见该函数末尾）。
             */
        },
        yAxis: {
            gridType: 'dash',
            gridColor: tokens.grid,
            splitNumber: 4
        },
        legend: {
            show: dual,
            fontColor: tokens.axisText
        }
        /*
         * ★★ 严禁在此处写 `tooltip` 键（踩坑记录，勿回退）：
         *   uCharts 的 `opts.tooltip` **不是**"气泡样式"，而是运行期交互状态槽 ——
         *   只有用户点选后由 `showToolTip()` 赋值 `{ textList, offset, index, group }`；
         *   未交互时它必须是 `undefined`，`drawActivePoint()` 才会在首行 `if(!opts.tooltip) return` 退出。
         *   一旦我们传入一个"只带颜色"的部分对象，它就变成 truthy，
         *   继续执行到 `opts.tooltip.group.length` ⇒ 抛
         *   `TypeError: Cannot read properties of undefined (reading 'length')`。
         *
         *   而折线/面积分支的 `onProcess` 顺序是：
         *     网格 → drawXAxis → drawLineDataPoints → **drawYAxis** → 图例 → `drawCanvas()`
         *   异常发生在 `drawLineDataPoints` 内部 ⇒ 其后（Y 轴刻度 / 图例 / 刷帧）全部跳过，
         *   画布停在**半渲染**：只剩网格 + 一条被压扁在底部的线、没有任何坐标轴刻度
         *   （实测折线纵向跨度仅 5px，对照柱状 282px）。柱状分支不调用 `drawActivePoint` ⇒ 不受影响，
         *   这正是"柱状正常、折线/双线全坏"的原因。
         *
         *   气泡样式（DESIGN.md §2.5：底 `--c-n-800`、字 `--c-n-0`）的**正确归属是
         *   `opts.extra.tooltip`** —— 见下方 `opts.extra.tooltip` 与 `drawToolTip()` 的取值处。
         */
    }

    const labelCount = labelCountForFit(days, captionPx, payload)
    if (labelCount) {
        opts.xAxis.labelCount = labelCount
    }
    if (captionPx) {
        opts.xAxis.fontSize = captionPx
    }

    /*
     * ★★ Y 轴文字样式（`fontColor` / `fontSize`）**必须写进 `yAxis.data[i]`** ——
     *    写在 `yAxis` 顶层是**死键**（踩坑记录，勿改回；与上一轮 `opts.tooltip` 同源：
     *    "配到库里根本不读的键位"）：
     *      ① `drawYAxis()` 读的是 `yData.fontColor` / `yData.fontSize`（`yData = opts.yAxis.data[i]`）；
     *      ② Y 轴的**预留宽度**也在 `calYAxisData()` 里按 `yData.fontSize * pix` 测量；
     *      ③ 只写顶层时：颜色回落库默认 `#666666`；字号回落 `config.fontSize`(13)，
     *         但**预留宽度仍按顶层那个字号测量** ⇒ 两条路径不一致
     *         ⇒ 实测 3 位数刻度左缘被裁（"130" 显示成 "30"、"111" 显示成 "11"）。
     *
     * ★ 为什么"只有血压被裁、柱状没事"：库模板 `column` 自带 `yAxis.data:[{min:0}]`
     *   ⇒ 走"有 data"分支、按 13px 测量 ⇒ 正常；而 `line` 模板**没有** `data`
     *   ⇒ 走"无 data"分支、只认顶层字号 ⇒ 被裁。
     *   这里显式给出 `data`，两种类型就都统一到「测量 = 绘制」同一字号。
     *
     * ★ 显式给 `data` 会替换/合并模板数组 ⇒ 柱状自带的 `min: 0` 必须自己补上，
     *   否则会丢掉 DESIGN.md §9「柱状图必须从 0 起」；折线（连续量）不设 min/max，
     *   沿用库的 `dataRange` 自动定界（§9「连续量可不从 0 起」）。
     */
    const yAxisData = {
        /** 与库模板 / 原行为一致：Y 轴刻度在左侧 */
        position: 'left',
        fontColor: tokens.axisText,
        /*
         * ★ 与 `xAxis.axisLineColor` 同理：`drawYAxis()` 画左侧轴线时读的是
         *   `yData.axisLineColor || '#cccccc'`（u-charts.js）⇒ 不显式给就落回灰。
         *   同色化后 Y 轴的"框架感"由横网格承担，符合 §9「不画竖网格」的克制取向。
         */
        axisLineColor: tokens.grid
    }
    if (captionPx) {
        yAxisData.fontSize = captionPx
    }
    if (chartType === 'column') {
        yAxisData.min = 0
    }
    opts.yAxis.data = [yAxisData]

    opts.extra = {}

    /*
     * 气泡样式（DESIGN.md §2.5 / §9：底 = `--c-n-800`、字 = `--c-n-0`）。
     * ★ 归属 `extra.tooltip` —— 这是 `drawToolTip()` / `drawToolTipSplitLine()` 的取值处，
     *   **不是** `opts.tooltip`（后者是运行期交互状态槽，见上方警告）。
     * ★ 必须自带 `legendShape`：uCharts 初始化执行
     *     `opts.extra = assign({ tooltip: { legendShape: 'auto' } }, opts.extra)`
     *   是**浅合并** ⇒ 我们给出的 `extra.tooltip` 会整体替换库默认值，
     *   而库内多处直接读 `opts.extra.tooltip.legendShape`（无兜底），故必须补齐。
     */
    opts.extra.tooltip = {
        legendShape: 'auto',
        bgColor: tokens.bubbleBg,
        fontColor: tokens.bubbleText,
        borderColor: tokens.bubbleBg
    }

    if (chartType === 'column') {
        /*
         * 柱状样式（S3-9 3.3 第3步）：
         *   - `type: 'group'`：与库模板一致（多系列并排；本工程柱状类只有单系列）；
         *   - `barBorderRadius`：**仅顶部两角**微圆角（2 CSS px × dpr），让细柱不至于像色块边界，
         *     达到"克制、现代"的观感。库要求数组长度为 4、单位为**设备像素**
         *     （内部按 `Math.min(width/2, height/2)` 夹取 ⇒ 极细柱自动退化为小圆角，不会画坏）。
         *   ★ 不启用 `linearType` 渐变：`linearType: 'opacity'` 会把柱顶降到半透明，
         *     30/90 天窗口的细柱（实测最细 1 设备 px）会因此更"发灰"，与本次目标相反。
         */
        const dpr = pixelRatio()
        opts.extra.column = { type: 'group' }
        if (dpr > 0) {
            const radius = Math.round(2 * dpr)
            opts.extra.column.barBorderRadius = [radius, radius, 0, 0]
        }
    } else {
        // 折线：直线段（不做曲线拟合，避免"看起来更平滑"的暗示）；选中点空心（白心 + 主色环）
        opts.extra.line = { type: 'straight', width: 2, activeType: 'hollow' }
    }

    const target = payload ? payload.target_line : null
    const targetValue = target ? toNumber(target.value) : null
    if (targetValue !== null) {
        opts.extra.markLine = {
            type: 'dash',
            data: [{
                value: targetValue,
                lineColor: tokens.goal,
                showLabel: false
            }]
        }
    }
    return opts
}

/** 供 C-23 判定的「本指标需要的系列色」（双线 2 个，其余 1 个） */
export function paletteOf(metricType, tokens) {
    const fields = POINT_FIELDS[metricType] || POINT_FIELDS.weight
    return fields.length > 1 ? [tokens.a, tokens.b] : [tokens.main]
}
