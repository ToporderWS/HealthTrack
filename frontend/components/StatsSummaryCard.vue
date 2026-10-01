<template>
    <!--
      C-24 StatsSummaryCard（统计摘要卡；DESIGN.md §8.3 已登记）

      规格（DESIGN.md §8.3 + S1-C SC-11 ⑤⑩）：
        **只允许** 6 项：平均 / 最高 / 最低 / 变化量 / 记录天数 / 达标率。
        **禁止** 健康度 / 评分 / 风险指数 / 是否正常 / 参考范围（DESIGN.md §12 红线）。

      ★ 与 S1-C SC-11 ⑩② 的关系：**记录数 < 2 时仅统计卡仍可展示数字**
        （图表区已提示「至少需要 2 条记录才能画出趋势」），故本组件不因 <2 条而隐藏数字。
      ★ 无记录 / 无同类目标时，对应数值显示 `—`（中性占位，与 C-21「静默显示 —」同口径），
        **不显示 0 冒充真实值、不显示任何评价性文案**。

      数值口径（**不改服务端实现，仅做展示层格式化**）：
        - `average` / `max` / `min` / `change.delta` 由 S-03 下发；均值可能是长小数
          （后端 `_mean` 返回 Decimal），展示层收敛到**最多 2 位小数并去掉末尾 0**；
        - 血压的 `average` 为收缩压均值，故成对展示 `average_systolic / average_diastolic`；
          `max` / `min` 在 S-03 中已是 `{systolic, diastolic, date}`，同样成对展示；
          `change` 基于收缩压日值，故该行标签明确写「变化（收缩压）」以免误读；
        - `recorded_days` 形如 `{recorded, total, percent}` → 展示「记录天数 recorded / total 天」；
        - `reached_rate_percent` 无同类目标时为 `null` → 展示 `—`。

      单位：由宿主页传入（血压 mmHg / 睡眠「小时」等），睡眠口径见 `utils/chartTheme.js` 的说明。

      八态：default（正常）/ loading（骨架）/ error（失败 + 重试）/ empty（全 `—`）
            pressed · disabled · success —— **N/A**（只读展示卡，无点击 / 无禁用 / 无成功语义）
            offline —— **N/A**（离线条与"离线只读"由宿主页与 C-23 承载，此处不重复）
    -->
    <AppCard :title="title" class="ssc">
        <view v-if="state === 'loading'">
            <AppSkeleton variant="card" />
        </view>

        <view v-else-if="state === 'error'">
            <AppErrorState
                variant="inline"
                :text="errorText"
                retry-text="重试"
                @retry="onRetry"
            />
        </view>

        <view v-else class="ssc__grid">
            <view v-for="row in rows" :key="row.key" class="ssc__item">
                <text class="ssc__label">{{ row.label }}</text>
                <view class="ssc__value-line">
                    <text class="ssc__value">{{ row.value }}</text>
                    <text v-if="row.unit" class="ssc__unit">{{ row.unit }}</text>
                </view>
            </view>
        </view>
    </AppCard>
</template>

<script>
import AppCard from './AppCard.vue'
import AppSkeleton from './AppSkeleton.vue'
import AppErrorState from './AppErrorState.vue'

import { chartUnit } from '../utils/chartTheme'

/** 缺失值的统一中性占位（DESIGN.md §8.3 C-21 同口径） */
const PLACEHOLDER = '—'

/**
 * 展示层数值格式化：最多 2 位小数并去掉末尾 0。
 * ★ 只在**展示**时收敛小数位；不参与任何计算，也不回写服务端。
 * @param {*} raw
 * @returns {string} 非法 / 缺失 → `—`
 */
function fmtNumber(raw) {
    if (raw === null || raw === undefined || raw === '') {
        return PLACEHOLDER
    }
    const n = Number(raw)
    if (isNaN(n)) {
        return PLACEHOLDER
    }
    const rounded = Math.round(n * 100) / 100
    return String(rounded)
}

/** 带符号增量：正数显式带 `+`，负数带 `-`；缺失 → `—` */
function fmtDelta(raw) {
    if (raw === null || raw === undefined || raw === '') {
        return PLACEHOLDER
    }
    const n = Number(raw)
    if (isNaN(n)) {
        return PLACEHOLDER
    }
    const text = fmtNumber(n)
    return n > 0 ? '+' + text : text
}

/** 「a / b」成对数值（血压）；任一缺失 → `—` */
function fmtPair(first, second) {
    if (first === null || first === undefined || second === null || second === undefined) {
        return PLACEHOLDER
    }
    return fmtNumber(first) + ' / ' + fmtNumber(second)
}

export default {
    name: 'StatsSummaryCard',
    components: {
        AppCard: AppCard,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState
    },
    props: {
        /** 卡片标题（默认取 S1-C SC-11 ⑤ 的区块名） */
        title: { type: String, default: '统计摘要' },
        /** 当前指标（8 类之一） */
        metricType: { type: String, default: '' },
        /** S-03 下发的单位（睡眠由 `chartUnit` 归一为「小时」，见 chartTheme 说明） */
        unitFromApi: { type: String, default: '' },
        /** S-03 的 `data.summary`；无数据 → null */
        summary: { type: Object, default: null },
        /** `loading` | `normal` | `error` */
        state: { type: String, default: 'normal' },
        /** 失败文案 */
        errorText: { type: String, default: '加载失败，点击重试' }
    },
    emits: ['retry'],
    computed: {
        /** 展示单位（血压 mmHg / 睡眠「小时」/ 其余取接口下发值） */
        unitText: function () {
            return chartUnit(this.metricType, this.unitFromApi)
        },
        /** 变化量行的标签：血压的 `change` 基于收缩压日值，需显式说明避免误读 */
        changeLabel: function () {
            return this.metricType === 'bp' ? '变化（收缩压）' : '变化'
        },
        /**
         * 6 行摘要（**顺序与 S1-C SC-11 ⑤ 一致，不增不减**）。
         * 说明：这里**不读**任何 extras（如 `average_quality` / `longest_streak_days` 等），
         * 因为它们不属于 §8.3 允许的 6 项，避免越过"只允许"边界。
         */
        rows: function () {
            const s = this.summary || {}
            const unit = this.unitText
            return [
                {
                    key: 'average',
                    label: '平均',
                    value: this.metricType === 'bp'
                        ? fmtPair(s.average_systolic, s.average_diastolic)
                        : fmtNumber(s.average),
                    unit: unit
                },
                {
                    key: 'max',
                    label: '最高',
                    value: this.metricType === 'bp'
                        ? fmtPair(s.max ? s.max.systolic : null, s.max ? s.max.diastolic : null)
                        : fmtNumber(s.max ? s.max.value : null),
                    unit: unit
                },
                {
                    key: 'min',
                    label: '最低',
                    value: this.metricType === 'bp'
                        ? fmtPair(s.min ? s.min.systolic : null, s.min ? s.min.diastolic : null)
                        : fmtNumber(s.min ? s.min.value : null),
                    unit: unit
                },
                {
                    key: 'change',
                    label: this.changeLabel,
                    value: fmtDelta(s.change ? s.change.delta : null),
                    unit: unit
                },
                {
                    key: 'days',
                    label: '记录天数',
                    value: this.daysText(s.recorded_days),
                    unit: ''
                },
                {
                    key: 'rate',
                    label: '达标率',
                    value: this.rateText(s.reached_rate_percent),
                    unit: ''
                }
            ]
        }
    },
    methods: {
        /** 「记录天数 R / T 天」；缺失 → `—` */
        daysText: function (days) {
            if (!days || days.recorded === null || days.recorded === undefined) {
                return PLACEHOLDER
            }
            return fmtNumber(days.recorded) + ' / ' + fmtNumber(days.total) + ' 天'
        },
        /** 「达标率 N%」；`null`（无同类目标 / 无记录）→ `—`（中性，不做任何评价） */
        rateText: function (rate) {
            if (rate === null || rate === undefined || rate === '') {
                return PLACEHOLDER
            }
            const n = Number(rate)
            if (isNaN(n)) {
                return PLACEHOLDER
            }
            return fmtNumber(n) + '%'
        },
        onRetry: function () {
            this.$emit('retry')
        }
    }
}
</script>

<style scoped lang="scss">
.ssc__grid {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
}

/* 2 列排布：窄屏（320px）下每列约 114px，「数值 + 单位」分两行不会溢出（与 SC-07 同口径） */
.ssc__item {
    display: flex;
    flex: 0 0 50%;
    flex-direction: column;
    padding-top: var(--sp-4);
    padding-bottom: var(--sp-4);
}

.ssc__label {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.ssc__value-line {
    display: flex;
    flex-direction: row;
    align-items: baseline;
    margin-top: var(--sp-1);
}

/* 统计摘要数字：DESIGN.md §3 `--fs-metric-l`（44rpx / 56rpx / 600） */
.ssc__value {
    font-size: var(--fs-metric-l);
    line-height: $lh-metric-l;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.ssc__unit {
    margin-left: var(--sp-2);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
