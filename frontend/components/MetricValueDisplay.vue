<template>
    <!--
      C-22 MetricValueDisplay（指标数值展示；DESIGN.md §8.3 已登记）
      规格：`--fs-display` 主值 + `--fs-sub` 单位 + 副值（舒张压 / 脉搏）+ `derived` 派生值
            （BMI / 睡眠时长）。**派生值只显示数字，无分级标签**（DESIGN.md §12 红线）。
      用途（S3-3）：SC-09 记录详情页的数值区。

      八态：default（有值）/ empty（主值缺失 → 显示「—」，属数据缺失的正常展示，非错误态）
            pressed · disabled · loading · error · success · offline —— **N/A**
            （**纯展示组件**：无数值交互、不承载请求；加载 / 失败 / 离线由宿主页承担。）

      ★ 红线（不得放宽）：
        1. **绝不**渲染正常 / 异常 / 偏高 / 偏低 / 参考范围 / 风险等级 —— 派生值只给数字；
        2. 主值缺失显示「—」而**不是 0**（避免把"没记录"伪装成"记了 0"）；
        3. 数值统一走全局 `tabular-nums`（DESIGN.md §3）。
    -->
    <view class="mvd">
        <view class="mvd__main">
            <text class="mvd__value" :class="{ 'mvd__value--empty': mainEmpty }">{{ mainText }}</text>
            <text v-if="unit" class="mvd__unit">{{ unit }}</text>
        </view>

        <!-- 副值行（如血压：舒张压 / 脉搏） -->
        <view v-if="subs.length" class="mvd__subs">
            <view v-for="(item, index) in subs" :key="'sub' + index" class="mvd__sub">
                <text class="mvd__sub-label">{{ item.label }}</text>
                <text class="mvd__sub-value">{{ item.value }}</text>
                <text v-if="item.unit" class="mvd__sub-unit">{{ item.unit }}</text>
            </view>
        </view>

        <!-- 派生值（BMI / 睡眠时长等；**只显示数字，无分级标签**） -->
        <view v-if="derived.length" class="mvd__derived">
            <view v-for="(item, index) in derived" :key="'der' + index" class="mvd__derived-item">
                <text class="mvd__derived-label">{{ item.label }}</text>
                <text class="mvd__derived-value">{{ item.value }}</text>
            </view>
        </view>
    </view>
</template>

<script>
export default {
    name: 'MetricValueDisplay',
    props: {
        /** 主值（数值或已格式化字符串；缺失 → 显示「—」） */
        value: { type: [String, Number], default: '' },
        /** 单位（由宿主页按接口下发值 / 冻结字典带入，组件不自行推导） */
        unit: { type: String, default: '' },
        /** 副值：`[{ label, value, unit }]`（如舒张压 / 脉搏；空数组 → 整区不渲染） */
        subs: { type: Array, default: function () { return [] } },
        /** 派生值：`[{ label, value }]`（如 BMI / 睡眠时长；**只给数字**） */
        derived: { type: Array, default: function () { return [] } }
    },
    computed: {
        mainEmpty: function () {
            return this.value === '' || this.value === null || this.value === undefined
        },
        mainText: function () {
            return this.mainEmpty ? '—' : String(this.value)
        }
    }
}
</script>

<style scoped lang="scss">
.mvd {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
}

.mvd__main {
    display: flex;
    flex-direction: row;
    align-items: baseline;
}

/* 主值：展示级大字阶（DESIGN.md §8.3 C-22 指定 --fs-display） */
.mvd__value {
    font-size: var(--fs-display);
    line-height: $lh-display;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.mvd__value--empty {
    color: var(--t-4);
}

.mvd__unit {
    margin-left: var(--sp-3);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-regular;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── 副值行 ── */
.mvd__subs {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    margin-top: var(--sp-4);
}

.mvd__sub {
    display: flex;
    flex-direction: row;
    align-items: baseline;
    margin-right: var(--sp-6);
    margin-bottom: var(--sp-2);
}

.mvd__sub-label {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.mvd__sub-value {
    margin-left: var(--sp-2);
    font-size: var(--fs-h3);
    line-height: $lh-h3;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.mvd__sub-unit {
    margin-left: var(--sp-1);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── 派生值行（只显示数字，无分级标签） ── */
.mvd__derived {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    margin-top: var(--sp-2);
}

.mvd__derived-item {
    display: flex;
    flex-direction: row;
    align-items: baseline;
    margin-right: var(--sp-6);
    margin-bottom: var(--sp-2);
}

.mvd__derived-label {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.mvd__derived-value {
    margin-left: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    font-weight: $fw-medium;
    color: var(--t-2);
    letter-spacing: 0;
}
</style>
