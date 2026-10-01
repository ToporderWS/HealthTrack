/**
 * 8 类健康指标的**录入表单契约**（纯字段与区间，**不含任何视觉取值**）。
 *
 * 权威来源（**逐格照抄，不得自行放宽 / 收紧**）：
 *   `backend/app/services/metric_rules.py`
 *   —— `METRIC_TYPES` / `METRIC_UNIT` / `MATRIX`（必填与禁止）/ `DECIMALS` / `DOMAIN_RANGE`
 *      / `HARD_RANGE` / `SOFT_RANGE` / `ATTR1_ENUM` / `ATTR2_ENUM` / `WATER_QUICK_ADD` / `validate_tags`。
 *
 * 用途（SC-08）：① 按 `type` 渲染字段；② 本地做**硬拦截级**预检（提交前拦住明显不可能的输入，
 * 少发无谓请求）。**服务端裁决为唯一权威**：本地校验通过不等于服务端一定通过。
 *
 * ★ 红线（不得放宽）：
 *   1. 本表的区间**只用于识别录入错误 / 不可能值**，**不是**任何医学参考区间；
 *   2. **禁止**把区间数值或任何"正常 / 异常 / 偏高 / 偏低 / 建议就医"文案渲染到界面
 *      （DESIGN.md §12）；越界一律只显示固定文案「数值超出常见范围，请确认是否输错」；
 *   3. **软提示**（超出常见范围但仍可能真实存在）由**服务端** `SOFT_WARNING` 裁决，
 *      客户端不重复判定，避免两套口径漂移。
 *
 * ★ 与你的任务描述的口径差异（如实登记）：本表 type 取值 = `bp` / `heart`，
 *   不使用 `blood_pressure` / `heart_rate`（后端 `METRIC_TYPES` 中不存在，提交会被 422）。
 */

/** 8 类指标（顺序 = 后端 `METRIC_TYPES`） */
export const FORM_TYPES = [
    'weight', 'bp', 'heart', 'glucose', 'sleep', 'water', 'sport', 'mood'
]

/**
 * 主数值区字段（`kind: 'main'` 的第一个字段用大号输入，其余用常规输入）。
 * 单位一律由服务端按指标填充（`METRIC_UNIT`），客户端只做展示，**不提交 `unit`**。
 */
export const MAIN_FIELDS = {
    weight: [{ field: 'value_1', label: '体重', required: true }],
    bp: [
        { field: 'value_1', label: '收缩压', required: true },
        { field: 'value_2', label: '舒张压', required: true }
    ],
    heart: [{ field: 'value_1', label: '心率', required: true }],
    glucose: [{ field: 'value_1', label: '血糖', required: true }],
    sleep: [],
    water: [{ field: 'value_1', label: '饮水量', required: true }],
    sport: [{ field: 'value_1', label: '运动时长', required: true }],
    mood: [{ field: 'value_1', label: '心情评分', required: true }]
}

/**
 * 指标专属字段区（按 `type` 动态渲染）。
 *   kind = number   数值输入
 *        | select   单选（options 来自 `R-08` 字典的 `enumKey`，**不在客户端硬编码枚举**）
 *        | datetime 时间选择（`YYYY-MM-DD HH:mm:ss`）
 *        | quick    快捷添加按钮（步进值来自 `R-08` 的 `water_quick_add`）
 *        | tags     多选标签（取值与上限来自 `R-08` 的 `mood_tags` 与 `validate_tags`）
 */
export const EXTRA_FIELDS = {
    bp: [
        { kind: 'number', field: 'value_3', label: '脉搏', unit: 'bpm', required: false },
        { kind: 'select', field: 'attr_1', label: '测量时机', enumKey: 'bp_timing', required: false }
    ],
    heart: [
        { kind: 'select', field: 'attr_1', label: '测量状态', enumKey: 'heart_state', required: false }
    ],
    glucose: [
        { kind: 'select', field: 'attr_1', label: '测量时机', enumKey: 'glucose_timing', required: true }
    ],
    sleep: [
        { kind: 'datetime', field: 'time_start', label: '入睡时间', required: true },
        { kind: 'datetime', field: 'recorded_at', label: '起床时间', required: true }
    ],
    water: [
        { kind: 'quick', label: '快捷添加', enumKey: 'water_quick_add', required: false }
    ],
    sport: [
        { kind: 'select', field: 'attr_1', label: '运动类型', enumKey: 'sport_type', required: true },
        { kind: 'select', field: 'attr_2', label: '运动强度', enumKey: 'sport_intensity', required: false }
    ],
    mood: [
        { kind: 'tags', field: 'tags', label: '感受标签', enumKey: 'mood_tags', required: false }
    ]
}

/**
 * 指标 → `attr_1` / `attr_2` 所属的**枚举字典名**（照抄后端 `metric_rules.ATTR1_ENUM` / `ATTR2_ENUM`）。
 *
 * 用途（S3-3 起）：SC-09 详情页把 `attr_1` / `attr_2` 的**枚举原始值**（如 `morning`）
 * 映射为中文标签；标签**只来自 `R-08` 字典缓存**（`kj:cache.record_options` 的 `enums`），
 * 缓存缺失时**静默隐藏该行**，不新增接口请求、不在客户端硬编码标签（避免与后端字典漂移）。
 */
export const ATTR1_ENUM = {
    bp: 'bp_timing',
    heart: 'heart_state',
    glucose: 'glucose_timing',
    sport: 'sport_type'
}

export const ATTR2_ENUM = { sport: 'sport_intensity' }

/** 感受标签所属字典名（照抄后端 `metric_rules.validate_tags` 读取的 `mood_tags`） */
export const TAGS_ENUM = 'mood_tags'

/**
 * 取某指标下某字段的**中文标签**（同时检索主数值区与专属字段区；未登记 → ''）。
 * 用途（S3-3）：SC-09 详情页字段列表的标签，**唯一来源仍是本契约表**，页面不得另立文案。
 * @param {string} metricType 8 类指标之一
 * @param {string} field 字段名（`value_1` / `value_2` / `attr_1` / `time_start` …）
 * @returns {string}
 */
export function fieldLabel(metricType, field) {
    const mains = MAIN_FIELDS[metricType] || []
    for (let i = 0; i < mains.length; i++) {
        if (mains[i].field === field) {
            return mains[i].label
        }
    }
    const extras = EXTRA_FIELDS[metricType] || []
    for (let i = 0; i < extras.length; i++) {
        if (extras[i].field === field) {
            return extras[i].label || ''
        }
    }
    return ''
}

/**
 * 取某指标下某字段所属的**枚举字典名**（`attr_1` / `attr_2` / `tags`）。
 * @returns {string} 未登记 → ''
 */
export function enumKeyOf(metricType, field) {
    if (field === 'attr_1') {
        return ATTR1_ENUM[metricType] || ''
    }
    if (field === 'attr_2') {
        return ATTR2_ENUM[metricType] || ''
    }
    if (field === 'tags') {
        return TAGS_ENUM
    }
    return ''
}

/**
 * 单位取值的**展示文案**（`value_3`「脉搏」用 bpm，其余沿用指标单位）。
 * @returns {string}
 */
export function fieldUnit(metricType, field) {
    const extras = EXTRA_FIELDS[metricType] || []
    for (let i = 0; i < extras.length; i++) {
        if (extras[i].field === field && extras[i].unit) {
            return extras[i].unit
        }
    }
    return ''
}

/**
 * 是否有独立「测量时间」行（`recorded_at`）。
 * `sleep` 的 `recorded_at` 语义是**起床时间**（S1-C SC-08 ③），已在专属字段区呈现，
 * 因此不再重复渲染通用时间行（避免同一字段出现两个输入点）。
 */
export const MEASURE_TIME_TYPES = ['weight', 'bp', 'heart', 'glucose', 'water', 'sport', 'mood']

/** 备注长度上限（后端 `validate_record`：> 200 → 422） */
export const NOTE_MAX = 200

/** 感受标签数量上限（后端 `validate_tags`：> 6 → 422） */
export const MOOD_TAG_MAX = 6

/** 小数位上限（后端 `DECIMALS`） */
export const DECIMALS = {
    weight: { value_1: 1 },
    bp: { value_1: 0, value_2: 0, value_3: 0 },
    heart: { value_1: 0 },
    glucose: { value_1: 1 },
    sleep: { value_1: 0 },
    water: { value_1: 0 },
    sport: { value_1: 0, value_2: 2 },
    mood: { value_1: 0 }
}

/** 定义域（枚举式数值，超出即非法 → 硬拦截；后端 `DOMAIN_RANGE`） */
export const DOMAIN_RANGE = {
    sleep: { value_1: { min: 1, max: 5 } },
    mood: { value_1: { min: 1, max: 5 } }
}

/** 明显不可能值（→ 硬拦截；后端 `HARD_RANGE`）。`null` = 该侧无界。 */
export const HARD_RANGE = {
    weight: { value_1: { min: 10, max: 500 } },
    bp: {
        value_1: { min: 30, max: 400 },
        value_2: { min: 20, max: 300 },
        value_3: { min: 20, max: 300 }
    },
    heart: { value_1: { min: 20, max: 300 } },
    glucose: { value_1: { min: 0, minInc: false, max: 50 } },
    water: { value_1: { min: 0, minInc: false, max: 5000 } },
    sport: { value_1: { min: 0, minInc: false, max: 1440 } }
}

/** 睡眠时长硬区间（小时，由 `time_start` 与 `recorded_at` 推导；后端 `SLEEP_DURATION_HARD_HOURS`） */
export const SLEEP_DURATION_HARD_HOURS = { min: 0, minInc: false, max: 24 }

/**
 * 「区间」判定（照抄后端 `metric_rules._check_range` 的边界语义）。
 * @param {number} value 数值
 * @param {object} range `{ min, max, minInc = true, maxInc = true }`；`null` 表示该侧无界
 * @returns {boolean} true = 落在区间内
 */
export function withinRange(value, range) {
    if (value === null || value === undefined || isNaN(value) || !range) {
        return false
    }
    if (range.min !== null && range.min !== undefined) {
        if (value < range.min) {
            return false
        }
        if (value === range.min && range.minInc === false) {
            return false
        }
    }
    if (range.max !== null && range.max !== undefined) {
        if (value > range.max) {
            return false
        }
        if (value === range.max && range.maxInc === false) {
            return false
        }
    }
    return true
}

/** 字符串/数字 → 数值；空 / 非法 → null（与 `validate.toNumber` 同口径，额外接受负号外的纯数字串） */
export function parseNumber(value) {
    const text = value === null || value === undefined ? '' : String(value).trim()
    if (!text) {
        return null
    }
    if (!/^-?\d+(\.\d+)?$/.test(text)) {
        return null
    }
    const num = Number(text)
    return isNaN(num) ? null : num
}

/** 小数位判定（照抄后端 `_too_many_decimals`：先归一化去尾随零） */
export function decimalsExceeded(value, allowed) {
    const num = parseNumber(value)
    if (num === null) {
        return false
    }
    const text = String(num)
    const dot = text.indexOf('.')
    if (dot < 0) {
        return false
    }
    const decimals = text.length - dot - 1
    return decimals > (allowed || 0)
}

/** 该指标的小数位上限（未登记字段 → null） */
export function decimalsOf(metricType, field) {
    const map = DECIMALS[metricType] || {}
    return map[field] === undefined ? null : map[field]
}

/**
 * 睡眠时长（小时，1 位小数；与后端 `sleep_duration_hours` 同口径）。
 * @param {string} start 入睡时间 `YYYY-MM-DD HH:mm(:ss)`
 * @param {string} end 起床时间
 * @returns {number|null}
 */
export function sleepDurationHours(start, end) {
    if (!start || !end) {
        return null
    }
    const from = parseStamp(start)
    const to = parseStamp(end)
    if (from === null || to === null || to <= from) {
        return null
    }
    return Math.round(((to - from) / 3600000) * 10) / 10
}

/** `YYYY-MM-DD HH:mm(:ss)` → 毫秒时间戳（按本地墙上时间解析，S1-D D-4；非法 → null） */
export function parseStamp(stamp) {
    const text = String(stamp || '').trim()
    const matched = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(text)
    if (!matched) {
        return null
    }
    const date = new Date(
        Number(matched[1]), Number(matched[2]) - 1, Number(matched[3]),
        Number(matched[4]), Number(matched[5]), Number(matched[6] || 0)
    )
    const time = date.getTime()
    return isNaN(time) ? null : time
}
