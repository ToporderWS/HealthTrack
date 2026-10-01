<template>
    <!--
      C-27 RecordItem（记录行）
      规格（DESIGN.md §8.3）：图标 + 主值 + 单位 + 次值 + 时间 `YYYY-MM-DD HH:mm`；
            variant = timeline（首页时间线，带节点连接线）/ list（历史列表，无连接线）。

      八态：default（有值）/ pressed（整行按下）
            empty（主值为 null → 显示「—」，属数据缺失的正常展示，非错误态）
            disabled · loading · error · success · offline —— **N/A**
            （加载 / 失败 / 离线由列表宿主页用 C-15 骨架 / C-16 失败态 / C-17 离线条表达。）

      图标 = **纯 CSS 几何构成**（DESIGN.md §2.5③：指标区分只靠 图标 + 文字标签 + 单位；
      8 类指标共用品牌色相，**不按指标换色**）。组件内零裸色值、零 emoji。

      ⚠️ 「次值」数据来源说明：S-01 的 `recent_records[]` **未下发 `value_2`**，
      故 SC-06 不传 `subValue`；组件能力已具备，供 S3-3 记录详情 / 历史列表按需启用。
    -->
    <view
        class="item"
        :class="'item--' + variant"
        hover-class="item--press"
        :hover-start-time="0"
        :hover-stay-time="80"
        @tap="handleTap"
    >
        <!-- 时间线节点：图标 + 向下连接线（最后一行不画线） -->
        <view class="item__node">
            <view class="item__icon">
                <view class="item__glyph" :class="'item__glyph--' + metricType">
                    <view class="item__g item__g--a"></view>
                    <view class="item__g item__g--b"></view>
                </view>
            </view>
            <view v-if="variant === 'timeline' && !last" class="item__line"></view>
        </view>

        <view class="item__body">
            <view class="item__head">
                <text class="item__name">{{ labelText }}</text>
                <view class="item__value">
                    <text class="item__number">{{ valueText }}</text>
                    <text v-if="unitText" class="item__unit">{{ unitText }}</text>
                </view>
            </view>
            <view class="item__foot">
                <text class="item__time">{{ timeText }}</text>
                <text v-if="subValue" class="item__sub">{{ subValue }}</text>
            </view>
        </view>
    </view>
</template>

<script>
import { metricLabel, metricUnit, toMinute } from '../utils/metrics'

export default {
    name: 'RecordItem',
    props: {
        /**
         * 记录对象（S-01 `recent_records[]` 的元素）：
         * `{ id, metric_type, value_1, unit, recorded_at, time_start, note, tags }`
         */
        record: { type: Object, default: function () { return {} } },
        /** timeline = 首页时间线；list = 历史列表 */
        variant: { type: String, default: 'timeline' },
        /** 是否为最后一行（timeline 下不绘制向下连接线） */
        last: { type: Boolean, default: false },
        /** 次值（S-01 未下发 value_2，缺省为空 → 不渲染） */
        subValue: { type: String, default: '' }
    },
    emits: ['tap'],
    computed: {
        metricType: function () {
            return String(this.record.metric_type || '')
        },
        labelText: function () {
            return metricLabel(this.metricType)
        },
        /** 主值缺失时显示「—」（**不显示 0**，避免把"没记录"伪装成"记了 0"） */
        valueText: function () {
            const v = this.record.value_1
            if (v === null || v === undefined || v === '') {
                return '—'
            }
            return String(v)
        },
        unitText: function () {
            return metricUnit(this.metricType, this.record.unit)
        },
        timeText: function () {
            return toMinute(this.record.recorded_at)
        }
    },
    methods: {
        handleTap: function () {
            this.$emit('tap', this.record)
        }
    }
}
</script>

<style scoped lang="scss">
.item {
    display: flex;
    flex-direction: row;
    align-items: stretch;
    min-height: var(--row-h);
    padding-top: var(--row-pad-y);
    padding-bottom: var(--row-pad-y);
    transition: background-color var(--d-row) var(--ease-std);
}

.item--press {
    background-color: var(--s-sunken);
}

.item__node {
    display: flex;
    flex-direction: column;
    align-items: center;
    margin-right: var(--sp-5);
}

.item__icon {
    width: 64rpx;
    height: 64rpx;
    border-radius: var(--r-full);
    background-color: var(--s-card-sub);
    border: 1rpx solid var(--b-line);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

/* timeline：图标下方的连接线（纯几何） */
.item__line {
    flex: 1;
    width: 2rpx;
    margin-top: var(--sp-2);
    background-color: var(--b-line);
}

/* ── 图标画布（几何构成，不引入图标库 / 图片素材 / emoji）
      图形只用 flex + 尺寸 + 令牌间距构成，**不使用绝对定位偏移**，避免引入非标间距值 ── */
.item__glyph {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    width: 32rpx;
    height: 32rpx;
}

.item__g {
    flex-shrink: 0;
    background-color: var(--c-p-600);
    border-radius: var(--r-xs);
}

/* 体重：圆盘 + 底座横条（纵排） */
.item__glyph--weight {
    flex-direction: column;
}

.item__glyph--weight .item__g--a {
    width: 16rpx;
    height: 16rpx;
    border-radius: var(--r-full);
}

.item__glyph--weight .item__g--b {
    width: 22rpx;
    height: 4rpx;
    margin-top: var(--sp-1);
}

/* 血压：两支不同高度的竖条（横排、底对齐） */
.item__glyph--bp {
    align-items: flex-end;
}

.item__glyph--bp .item__g--a {
    width: 6rpx;
    height: 16rpx;
}

.item__glyph--bp .item__g--b {
    width: 6rpx;
    height: 24rpx;
    margin-left: var(--sp-2);
}

/* 心率：脉冲点 + 竖直指示线（横排） */
.item__glyph--heart .item__g--a {
    width: 13rpx;
    height: 13rpx;
    border-radius: var(--r-full);
}

.item__glyph--heart .item__g--b {
    width: 4rpx;
    height: 22rpx;
    margin-left: var(--sp-2);
}

/* 血糖：单支竖圆条（试管外形） */
.item__glyph--glucose .item__g--a {
    width: 10rpx;
    height: 27rpx;
    border-radius: var(--r-full);
}

.item__glyph--glucose .item__g--b {
    display: none;
}

/* 睡眠：两条不同长度的横线（纵排、左对齐） */
.item__glyph--sleep {
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
}

.item__glyph--sleep .item__g--a {
    width: 24rpx;
    height: 5rpx;
}

.item__glyph--sleep .item__g--b {
    width: 14rpx;
    height: 5rpx;
    margin-top: var(--sp-1);
}

/* 饮水：竖椭圆（水滴简化形） */
.item__glyph--water .item__g--a {
    width: 14rpx;
    height: 27rpx;
    border-radius: var(--r-full);
}

.item__glyph--water .item__g--b {
    display: none;
}

/* 运动：斜向圆角条（角度属图标几何，不计入比例值判据） */
.item__glyph--sport .item__g--a {
    width: 26rpx;
    height: 7rpx;
    transform: rotate(-45deg);
}

.item__glyph--sport .item__g--b {
    display: none;
}

/* 心情：实心圆点 */
.item__glyph--mood .item__g--a {
    width: 20rpx;
    height: 20rpx;
    border-radius: var(--r-full);
}

.item__glyph--mood .item__g--b {
    display: none;
}

/* ── 右侧内容 ── */
.item__body {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
}

.item__head {
    display: flex;
    flex-direction: row;
    align-items: baseline;
    justify-content: space-between;
}

.item__name {
    font-size: var(--fs-h3);
    line-height: $lh-h3;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.item__value {
    display: flex;
    flex-direction: row;
    align-items: baseline;
}

/* 数值：tabular-nums 由全局重置保证（DESIGN.md §3） */
.item__number {
    font-size: var(--fs-metric-l);
    line-height: $lh-metric-l;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.item__unit {
    margin-left: var(--sp-1);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-regular;
    color: var(--t-3);
    letter-spacing: 0;
}

.item__foot {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    margin-top: var(--sp-1);
}

.item__time {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.item__sub {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
