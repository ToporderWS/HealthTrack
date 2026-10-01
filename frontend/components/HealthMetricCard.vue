<template>
    <!--
      C-21 HealthMetricCard（记录中心网格卡，DESIGN.md §8.3 已登记）
      规格：图标 + 指标名 + 单位 + 【记一笔】 + 右上【历史】；**最近值区取不到时静默显示 `—`**。
            **不得出现"自定义指标"卡**（F-029 属 P1）。

      八态：default（可点）/ pressed（卡片按下）/ empty（最近值缺失 → 显示「—」，属数据缺失的正常展示）
            disabled（【历史】入口在 SC-10 落地前**置灰且不派发事件**）
            loading · error · success · offline —— **N/A**
            （本卡不承载请求：最近值由宿主页从本地缓存带入；无值即「—」，不弹错、不阻塞录入。）

      图标 = **纯 CSS 几何构成**，与 C-27 `RecordItem` 共用同一套图形语言
      （DESIGN.md §2.5③：8 类指标共用品牌色相，只靠 图标 + 文字标签 + 单位 区分）。

      ★ 如实登记：`historyEnabled=false` 时【历史】保留完整视觉但**不派发 `history` 事件**
        —— 记录历史页 SC-10 属 S3-3，按既有裁定（未实现页面不建立跳转、不造死链）处理；
        S3-3 落地后由宿主页传 `history-enabled` 即可接通，本组件零改动。
    -->
    <view
        class="mcard"
        hover-class="mcard--press"
        :hover-start-time="0"
        :hover-stay-time="80"
        @tap="handleRecord"
    >
        <view class="mcard__head">
            <view class="mcard__icon">
                <view class="mcard__glyph" :class="'mcard__glyph--' + metricType">
                    <view class="mcard__g mcard__g--a"></view>
                    <view class="mcard__g mcard__g--b"></view>
                </view>
            </view>

            <view
                class="mcard__history"
                :class="{ 'mcard__history--disabled': !historyEnabled }"
                :hover-class="historyEnabled ? 'mcard__history--press' : 'none'"
                :hover-start-time="0"
                :hover-stay-time="80"
                @tap.stop="handleHistory"
            >
                <text class="mcard__history-text">历史</text>
            </view>
        </view>

        <view class="mcard__name-row">
            <text class="mcard__name">{{ label }}</text>
            <text v-if="unit" class="mcard__unit">{{ unit }}</text>
        </view>

        <!-- 最近值（取不到 → 「—」；**不显示 0**，避免把"没记录"伪装成"记了 0"） -->
        <text class="mcard__recent">最近 {{ recentText }}</text>
        <text v-if="recentTime" class="mcard__recent-time">{{ recentTime }}</text>

        <view class="mcard__cta">
            <text class="mcard__cta-text">记一笔</text>
        </view>
    </view>
</template>

<script>
export default {
    name: 'HealthMetricCard',
    props: {
        /** 指标类型（8 类之一，取值与后端 `METRIC_TYPES` 一致） */
        metricType: { type: String, default: '' },
        /** 指标中文名 */
        label: { type: String, default: '' },
        /** 单位（单位来自冻结字典 / 接口下发，组件不自行推导） */
        unit: { type: String, default: '' },
        /** 最近值文案（如 `72.5 kg`）；空 → 显示「—」 */
        recent: { type: String, default: '' },
        /**
         * 最近值的时间（如 `09-15 08:30`，由宿主页用 `toShortMinute` 裁好）。
         * 单独一行渲染：2 列卡在 320px 屏内宽仅约 114px，与值同行必然折行/溢出。
         * 为空则**整行不渲染**（无值时不出现空行）。
         */
        recentTime: { type: String, default: '' },
        /** 【历史】入口是否可点（SC-10 落地前恒为 false） */
        historyEnabled: { type: Boolean, default: false }
    },
    emits: ['record', 'history'],
    computed: {
        recentText: function () {
            return this.recent ? String(this.recent) : '—'
        }
    },
    methods: {
        handleRecord: function () {
            this.$emit('record', this.metricType)
        },
        handleHistory: function () {
            // 未实现页面的入口：不派发事件（无死链、无假页面、无"敬请期待"占位）
            if (!this.historyEnabled) {
                return
            }
            this.$emit('history', this.metricType)
        }
    }
}
</script>

<style scoped lang="scss">
.mcard {
    width: calc((100% - var(--card-gap)) / 2);
    box-sizing: border-box;
    margin-bottom: var(--card-gap);
    padding: var(--card-pad);
    border-radius: var(--r-md);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-line);
    box-shadow: var(--el-0);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.mcard--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.mcard__head {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
}

/* 图标容器（与 C-27 同构：圆形底 + 1rpx 描边） */
.mcard__icon {
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

/* ── 图标画布（几何构成，不引入图标库 / 图片素材 / emoji）
      图形只用 flex + 尺寸 + 令牌间距构成，**不使用绝对定位偏移**，避免引入非标间距值 ── */
.mcard__glyph {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    width: 32rpx;
    height: 32rpx;
}

.mcard__g {
    flex-shrink: 0;
    background-color: var(--c-p-600);
    border-radius: var(--r-xs);
}

/* 体重：圆盘 + 底座横条（纵排） */
.mcard__glyph--weight {
    flex-direction: column;
}

.mcard__glyph--weight .mcard__g--a {
    width: 16rpx;
    height: 16rpx;
    border-radius: var(--r-full);
}

.mcard__glyph--weight .mcard__g--b {
    width: 22rpx;
    height: 4rpx;
    margin-top: var(--sp-1);
}

/* 血压：两支不同高度的竖条（横排、底对齐） */
.mcard__glyph--bp {
    align-items: flex-end;
}

.mcard__glyph--bp .mcard__g--a {
    width: 6rpx;
    height: 16rpx;
}

.mcard__glyph--bp .mcard__g--b {
    width: 6rpx;
    height: 24rpx;
    margin-left: var(--sp-2);
}

/* 心率：脉冲点 + 竖直指示线（横排） */
.mcard__glyph--heart .mcard__g--a {
    width: 13rpx;
    height: 13rpx;
    border-radius: var(--r-full);
}

.mcard__glyph--heart .mcard__g--b {
    width: 4rpx;
    height: 22rpx;
    margin-left: var(--sp-2);
}

/* 血糖：单支竖圆条（试管外形） */
.mcard__glyph--glucose .mcard__g--a {
    width: 10rpx;
    height: 27rpx;
    border-radius: var(--r-full);
}

.mcard__glyph--glucose .mcard__g--b {
    display: none;
}

/* 睡眠：两条不同长度的横线（纵排、左对齐） */
.mcard__glyph--sleep {
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
}

.mcard__glyph--sleep .mcard__g--a {
    width: 24rpx;
    height: 5rpx;
}

.mcard__glyph--sleep .mcard__g--b {
    width: 14rpx;
    height: 5rpx;
    margin-top: var(--sp-1);
}

/* 饮水：竖椭圆（水滴简化形） */
.mcard__glyph--water .mcard__g--a {
    width: 14rpx;
    height: 27rpx;
    border-radius: var(--r-full);
}

.mcard__glyph--water .mcard__g--b {
    display: none;
}

/* 运动：斜向圆角条（角度属图标几何，不计入比例值判据） */
.mcard__glyph--sport .mcard__g--a {
    width: 26rpx;
    height: 7rpx;
    transform: rotate(-45deg);
}

.mcard__glyph--sport .mcard__g--b {
    display: none;
}

/* 心情：实心圆点 */
.mcard__glyph--mood .mcard__g--a {
    width: 20rpx;
    height: 20rpx;
    border-radius: var(--r-full);
}

.mcard__glyph--mood .mcard__g--b {
    display: none;
}

/* ── 右上【历史】入口（热区 ≥ --tap-min） ── */
.mcard__history {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: flex-end;
    min-height: var(--tap-min);
    padding-left: var(--sp-4);
}

.mcard__history-text {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-link);
    letter-spacing: 0;
}

/* 未实现页面的入口：置灰（用次要文字色表达，不用透明度） */
.mcard__history--disabled .mcard__history-text {
    color: var(--t-4);
}

.mcard__history--press {
    opacity: var(--press-opacity);
}

/* ── 名称 + 单位 ── */
.mcard__name-row {
    display: flex;
    flex-direction: row;
    align-items: baseline;
    margin-top: var(--sp-4);
}

.mcard__name {
    font-size: var(--fs-h3);
    line-height: $lh-h3;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.mcard__unit {
    margin-left: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.mcard__recent {
    display: block;
    margin-top: var(--sp-1);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
    /* 极窄屏兜底：单行不折行、超出裁切（值本身很短，正常屏不会触发） */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.mcard__recent-time {
    display: block;
    margin-top: var(--sp-1);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-4);
    letter-spacing: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* ── 【记一笔】 ── */
.mcard__cta {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-height: var(--tap-min);
    margin-top: var(--sp-5);
    border-radius: var(--r-md);
    background-color: var(--s-brand-soft);
}

.mcard__cta-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--c-p-600);
    letter-spacing: 0;
}
</style>
