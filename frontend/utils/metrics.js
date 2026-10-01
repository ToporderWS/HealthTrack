/**
 * 指标 / 目标的**展示字典**（纯文案与单位映射，不含任何视觉取值）。
 *
 * 权威来源（逐字对齐，**不得在客户端另立一套**）：
 *   - 指标与单位：后端 `app/services/metric_rules.py` 的 `METRIC_TYPES` / `METRIC_UNIT`
 *     （weight kg / bp mmHg / heart bpm / glucose mmol/L / sleep score / water ml / sport min / mood score）；
 *   - 目标类型：后端 `app/services/goal_service.py` 的 `GOAL_TYPES`
 *     （weight / water / sport / sleep —— **仅这 4 类**，客户端不得扩展）；
 *   - 目标标签：与 S3-1 已交付的 SC-05 第 4 步逐字一致。
 *
 * 红线（DESIGN.md §12）：标签只陈述"记录了什么"，**不得**出现正常 / 异常 / 偏高 / 偏低
 *   等医学判断，也不得附带任何参考范围。
 */

/** 8 类指标 → 中文名（顺序 = 后端 `METRIC_TYPES`，用于确定性渲染） */
export const METRIC_TYPES = [
    'weight', 'bp', 'heart', 'glucose', 'sleep', 'water', 'sport', 'mood'
]

export const METRIC_LABEL = {
    weight: '体重',
    bp: '血压',
    heart: '心率',
    glucose: '血糖',
    sleep: '睡眠',
    water: '饮水',
    sport: '运动',
    mood: '心情'
}

/** 8 类指标 → 单位（与后端 `METRIC_UNIT` 逐字一致；接口下发 `unit` 时以接口为准） */
export const METRIC_UNIT = {
    weight: 'kg',
    bp: 'mmHg',
    heart: 'bpm',
    glucose: 'mmol/L',
    sleep: 'score',
    water: 'ml',
    sport: 'min',
    mood: 'score'
}

/** 首页 4 个快捷录入卡（DESIGN.md §8.3 C-28 冻结清单，顺序不可改） */
export const QUICK_METRICS = ['weight', 'bp', 'water', 'sport']

/**
 * `value_2` / `value_3` 的**展示标签**（仅供 SC-09 详情页副值区使用）。
 *
 * 权威来源（**逐字对齐，不自行发明**）：S1-B 第二批 §七 R-01 请求参数表 ——
 *   `value_2` = 「血压舒张压 / 运动卡路里」；`value_3` = 「血压脉搏」。
 *
 * ★ 与 SC-08 表单契约的分工（**不得混用**）：
 *   SC-08 的字段渲染只读 `utils/recordForm.js` 的 `MAIN_FIELDS` / `EXTRA_FIELDS`；
 *   本表**只用于详情页展示**（因为 SC-08 未采集「运动卡路里」，故它不在表单契约里）。
 *   本表**不参与任何表单渲染**，改它不会影响 SC-08。
 */
export const VALUE_FIELD_LABEL = {
    bp: { value_2: '舒张压', value_3: '脉搏' },
    sport: { value_2: '卡路里' }
}

/** 4 类目标 → 中文名（与 SC-05 第 4 步标签一致） */
export const GOAL_LABEL = {
    weight: '目标体重',
    water: '每日饮水',
    sport: '每周运动',
    sleep: '每日睡眠'
}

/** 指标中文名；未知类型原样回显（不隐藏数据，也不编造名称） */
export function metricLabel(type) {
    return METRIC_LABEL[type] || String(type || '')
}

/** 指标单位；优先用接口下发的 unit，缺省回退到冻结字典 */
export function metricUnit(type, unitFromApi) {
    if (unitFromApi) {
        return String(unitFromApi)
    }
    return METRIC_UNIT[type] || ''
}

/** 目标中文名；未知类型原样回显 */
export function goalLabel(type) {
    return GOAL_LABEL[type] || metricLabel(type)
}

/**
 * 目标单位 → 中文（SC-12 / SC-13 的上屏口径）。
 *
 * 取值域**完全来自后端** `goal_service.UNIT_BY_TYPE` / `SPORT_UNITS`
 *   （`kg` / `ml` / `hour` / `min` / `count`）—— 不扩展、不发明新单位。
 * 用途：① `GoalProgressCard` 的「还差 X」把服务端下发的英文单位词换成中文；
 *       ② SC-13 目标值输入框的单位后缀。
 * 红线（DESIGN.md §12）：只做「单位词中文化」，**不改数值、不加任何评价词**。
 */
export const GOAL_UNIT_LABEL = {
    kg: '千克',
    ml: '毫升',
    hour: '小时',
    min: '分钟',
    count: '次'
}

/** 目标单位中文名；未知单位**原样回显**（不隐藏数据，也不猜测含义） */
export function goalUnitLabel(unit) {
    return GOAL_UNIT_LABEL[unit] || String(unit || '')
}

/**
 * 时间戳裁剪：`YYYY-MM-DD HH:mm:ss` → `YYYY-MM-DD HH:mm`（DESIGN.md §8.3 C-27 冻结格式）。
 * 服务端时间口径为"本地墙上时间、无时区后缀"（S1-D D-4），因此**只做字符串裁剪**，
 * 不做任何时区换算。
 */
export function toMinute(stamp) {
    if (!stamp) {
        return ''
    }
    return String(stamp).slice(0, 16)
}

/** 时间戳裁剪：`YYYY-MM-DD HH:mm:ss` → `YYYY-MM-DD` */
export function toDay(stamp) {
    if (!stamp) {
        return ''
    }
    return String(stamp).slice(0, 10)
}

/**
 * 时间戳裁剪：`YYYY-MM-DD HH:mm:ss` → `MM-DD HH:mm`。
 * 用途：**窄容器**（如 SC-07 的 2 列指标卡，320px 屏内宽约 114px）——
 * 完整 `YYYY-MM-DD HH:mm` 会折行甚至溢出，故只做**同一冻结格式的截断**
 * （非新格式、无时区换算、无相对时间推算）。
 */
export function toShortMinute(stamp) {
    if (!stamp) {
        return ''
    }
    const text = String(stamp)
    return text.length >= 16 ? text.slice(5, 16) : text
}
