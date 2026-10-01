<template>
    <!--
      C-25 GoalProgressCard（今日目标进度卡）
      规格（DESIGN.md §8.3）：环形 + 进度条 + 「当前值 / 目标值」+ **中性文案「还差 500 ml」**
            + 状态标签（进行中 / 已暂停）。

      八态：default（进行中）/ pressed（整卡按下）/ success → **N/A**（"已达成"用**品牌色**标签表达，
            不使用 `--c-success`：语义色只用于"系统反馈"，不得用于健康/目标结果的好坏判断，§2.3/§12）
            disabled · loading · error · empty · offline —— **N/A**（加载/失败/空/离线由宿主页表达）

      数据来源：
        · S-01 的 `goals[]`（首页 SC-06，只读复用 G-07）；
        · **S3-5 起** SC-12 目标页也会传入（G-01 + G-07 合并后的对象，字段是超集）。

      ★ 如实登记（S3-5 更新，两处）：
        1. **状态（`status` 可选 prop）**：`1` = 进行中 / `0` = 已暂停（后端数字枚举）。
           - **不传（默认 `null`）⇒ 行为与 S3-2 完全一致**（首页 SC-06 未传该 prop，零影响）；
           - 传 `0` → 标签「已暂停」（中性灰底，**不叠加**品牌浅底）。
           - ⚠️ **不得**直接用服务端 `status_text` 上屏：它是英文枚举
             （`ongoing` / `paused` / `archived`），不是展示文案。
           状态映射：已暂停 → 「已暂停」；`is_reached` → 「已达成」；否则 → 「进行中」。
        2. **「还差 X」文案**：数值**保持服务端下发的原样**，只把尾部**英文单位词**换成中文
           （服务端模板为 `还差 {数值} {unit}`，`unit` ∈ `kg/ml/hour/min/count`）⇒ 避免中英混杂；
           **已达成时不再显示「还差 0 X」**，改用中性陈述「**目标已完成**」（S3-5 裁定）。
           未达成文案只作中性陈述，**不含任何评价词 / 医学结论**（DESIGN.md §12）。
    -->
    <view
        class="goal"
        hover-class="goal--press"
        :hover-start-time="0"
        :hover-stay-time="80"
        @tap="handleTap"
    >
        <view class="goal__ring">
            <ProgressRing :percent="percent" size="m">
                <text class="goal__percent">{{ percentText }}</text>
            </ProgressRing>
        </view>

        <view class="goal__main">
            <view class="goal__head">
                <text class="goal__name">{{ labelText }}</text>
                <view class="goal__chip" :class="{ 'goal__chip--reached': chipReached }">
                    <text class="goal__chip-text">{{ statusText }}</text>
                </view>
            </view>

            <text class="goal__values">
                {{ currentText }} / {{ targetText }} {{ unitText }}
            </text>

            <text class="goal__remaining">{{ remainingText }}</text>

            <view class="goal__track">
                <view class="goal__fill" :style="{ width: fillWidth }"></view>
            </view>
        </view>
    </view>
</template>

<script>
import ProgressRing from './ProgressRing.vue'
import { goalLabel, goalUnitLabel } from '../utils/metrics'

export default {
    name: 'GoalProgressCard',
    components: {
        ProgressRing: ProgressRing
    },
    props: {
        /**
         * 目标对象：
         *   · 首页（S-01 `goals[]`）：
         *     `{ goal_id, goal_type, target_value, current_value, unit, progress_percent, is_reached, remaining_text }`
         *   · SC-12（G-01 + G-07 合并）：上述字段 + `status` / `attr_1` / `rate` 等（多出字段本组件不使用）
         */
        goal: { type: Object, default: function () { return {} } },
        /**
         * 目标状态（**可选**，S3-5 新增）：`1` = 进行中 / `0` = 已暂停（后端数字枚举）。
         *
         * **不传 / 传 `null`** ⇒ 状态未知，行为与 S3-2 完全一致（不会显示「已暂停」）；
         * 传 `0` ⇒ 标签显示「已暂停」。
         */
        status: { type: [Number, String], default: null }
    },
    emits: ['tap'],
    computed: {
        labelText: function () {
            return goalLabel(this.goal.goal_type)
        },
        reached: function () {
            return this.goal.is_reached === true
        },
        /**
         * 是否已暂停。
         * 仅当调用方**显式传了**可解析的 `status` 且值为 `0` 时成立；
         * 未传（`null`）时恒为 `false` ⇒ 旧调用方（首页）行为不受影响。
         */
        paused: function () {
            const raw = this.status
            if (raw === null || raw === undefined || raw === '') {
                return false
            }
            const n = Number(raw)
            return !isNaN(n) && n === 0
        },
        rawPercent: function () {
            const n = Number(this.goal.progress_percent)
            return isNaN(n) ? 0 : n
        },
        percent: function () {
            if (this.rawPercent < 0) {
                return 0
            }
            return this.rawPercent > 100 ? 100 : this.rawPercent
        },
        /** 环心百分比：整数显示（数值为服务端口径，客户端只做取整展示） */
        percentText: function () {
            return String(Math.round(this.rawPercent)) + '%'
        },
        /** 进度条宽度：数据驱动（非设计令牌），沿用 SC-05 既有的 inline width 口径 */
        fillWidth: function () {
            return this.percent + '%'
        },
        currentText: function () {
            return formatNumber(this.goal.current_value)
        },
        targetText: function () {
            return formatNumber(this.goal.target_value)
        },
        unitText: function () {
            return this.goal.unit ? String(this.goal.unit) : ''
        },
        /**
         * 「还差 X」/「目标已完成」。
         * 保护口径：服务端未下发（`null` / 空）⇒ 返回空串，**不渲染该行**，绝不补 0。
         */
        remainingText: function () {
            if (this.reached) {
                return '目标已完成'
            }
            return localizeRemaining(this.goal.remaining_text, goalUnitLabel(this.goal.unit))
        },
        /** 状态标签：已暂停 > 已达成 > 进行中 */
        statusText: function () {
            if (this.paused) {
                return '已暂停'
            }
            return this.reached ? '已达成' : '进行中'
        },
        /** 是否套用「已达成」的品牌浅底（已暂停时不套用，避免样式与状态语义冲突） */
        chipReached: function () {
            return this.reached && !this.paused
        }
    },
    methods: {
        handleTap: function () {
            this.$emit('tap', this.goal)
        }
    }
}

/** 数值展示：null / 缺失 → 「—」；其余原样（不补零、不四舍五入，避免篡改服务端口径） */
function formatNumber(value) {
    if (value === null || value === undefined || value === '') {
        return '—'
    }
    return String(value)
}

/**
 * 把服务端「还差 {数值} {unit}」里的**英文单位词换成中文**（数值保持服务端原样）。
 *
 * 为什么不由客户端重拼数字：服务端 `_num()` 已统一 int / float 与数值口径
 *   （如「还差 0.2 hour」），重拼会引入第二套数字口径。
 * 为什么必须换单位：服务端模板用的是英文枚举单位 `kg/ml/hour/min/count`，
 *   直接上屏会出现中英混杂（S3-5 裁定：界面显示中文单位）。
 * 容错：尾部**没有**英文单位词时**原样返回**（不追加、不猜测），不制造第二套口径。
 *
 * @param {string} text 服务端 `remaining_text`
 * @param {string} unitCn 中文单位（来自 `goalUnitLabel`）
 * @returns {string} 本地化文案；无有效输入 → `''`（调用方据此不渲染该行）
 */
function localizeRemaining(text, unitCn) {
    const raw = text === null || text === undefined ? '' : String(text).trim()
    if (!raw) {
        return ''
    }
    if (!unitCn) {
        return raw
    }
    const tail = /\s+[A-Za-z]+\s*$/
    if (!tail.test(raw)) {
        return raw
    }
    return raw.replace(tail, '') + ' ' + unitCn
}
</script>

<style scoped lang="scss">
.goal {
    display: flex;
    flex-direction: row;
    align-items: center;
    padding: var(--card-pad);
    border-radius: var(--r-md);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-line);
    box-shadow: var(--el-0);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.goal--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.goal__ring {
    margin-right: var(--sp-5);
    flex-shrink: 0;
}

.goal__percent {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.goal__main {
    flex: 1;
}

.goal__head {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
}

.goal__name {
    font-size: var(--fs-h3);
    line-height: $lh-h3;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

/* 状态标签：中性灰底（进行中 / 已暂停）/ 品牌浅底（已达成）——不涉及健康好坏语义 */
.goal__chip {
    padding: var(--sp-1) var(--sp-3);
    border-radius: var(--r-xs);
    background-color: var(--s-card-sub);
}

.goal__chip--reached {
    background-color: var(--s-brand-soft);
}

.goal__chip-text {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.goal__chip--reached .goal__chip-text {
    color: var(--c-p-600);
}

.goal__values {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.goal__remaining {
    display: block;
    margin-top: var(--sp-1);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    letter-spacing: 0;
}

/* 进度条：品牌色进度 + --c-n-100 轨道（与 C-26 同色口径） */
.goal__track {
    margin-top: var(--sp-4);
    height: 12rpx;
    border-radius: var(--r-full);
    background-color: var(--s-sunken);
    overflow: hidden;
}

.goal__fill {
    height: 100%;
    border-radius: var(--r-full);
    background-color: var(--c-p-600);
    transition: width var(--d-base) var(--ease-std);
}
</style>
