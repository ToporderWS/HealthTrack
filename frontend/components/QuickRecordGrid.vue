<template>
    <!--
      C-28 QuickRecordGrid（首页 4 快捷录入卡）
      规格（DESIGN.md §8.3）：首页 4 快捷卡（**体重 / 血压 / 饮水 / 运动**，清单冻结不可增删）；
            **空状态时同时高亮 4 卡**（SC-06 ⑩ 的"首次使用"引导）。

      八态：default / pressed（卡片按下）/ empty（highlight = true → 4 卡同时高亮，即"首次使用"引导态）
            disabled · loading · error · success · offline —— **N/A**
            （快捷卡本身是**入口**，无数据、无写操作；加载 / 失败 / 离线由宿主页表达。）

      图标 = 纯 CSS 几何构成，与 C-27 保持同一套图形语言（组件内零裸色值、零 emoji、零图片素材）。
      ⚠️ 未实现目标页时的处理：本批 `pages/record/add`(SC-08) 尚未实现，
      宿主页（SC-06）对 select 事件**不做跳转**，本组件只负责"呈现 + 上报点击"。
    -->
    <view class="quick">
        <view
            v-for="item in list"
            :key="item.type"
            class="quick__card"
            :class="{ 'quick__card--highlight': highlight }"
            hover-class="quick__card--press"
            :hover-start-time="0"
            :hover-stay-time="80"
            @tap="handleTap(item)"
        >
            <view class="quick__top">
                <view class="quick__glyph" :class="'quick__glyph--' + item.type">
                    <view class="quick__g quick__g--a"></view>
                    <view class="quick__g quick__g--b"></view>
                </view>
                <text class="quick__unit">{{ item.unit }}</text>
            </view>

            <text class="quick__name">{{ item.label }}</text>

            <view class="quick__cta">
                <text class="quick__cta-text">记一笔</text>
            </view>
        </view>
    </view>
</template>

<script>
import { QUICK_METRICS, metricLabel, METRIC_UNIT } from '../utils/metrics'

export default {
    name: 'QuickRecordGrid',
    props: {
        /** 空状态（首次使用）时置 true → 4 卡同时高亮（SC-06 ⑩） */
        highlight: { type: Boolean, default: false }
    },
    emits: ['select'],
    computed: {
        list: function () {
            return QUICK_METRICS.map(function (type) {
                return {
                    type: type,
                    label: metricLabel(type),
                    unit: METRIC_UNIT[type]
                }
            })
        }
    },
    methods: {
        handleTap: function (item) {
            this.$emit('select', item)
        }
    }
}
</script>

<style scoped lang="scss">
.quick {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: space-between;
}

.quick__card {
    width: calc((100% - var(--card-gap)) / 2);
    box-sizing: border-box;
    margin-bottom: var(--card-gap);
    padding: var(--card-pad);
    border-radius: var(--r-md);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-line);
    box-shadow: var(--el-0);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std),
        background-color var(--d-base) var(--ease-std);
}

.quick__card--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

/* 首次使用：4 卡同时高亮（品牌浅底 + 品牌描边；属于"可交互/已选中"用途） */
.quick__card--highlight {
    background-color: var(--s-brand-soft);
    border: 1rpx solid var(--c-p-600);
}

.quick__top {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
}

/* ── 图标画布（与 C-27 同一套几何语言）
      图形只用 flex + 尺寸 + 令牌间距构成，**不使用绝对定位偏移**，避免引入非标间距值 ── */
.quick__glyph {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    width: 32rpx;
    height: 32rpx;
}

.quick__g {
    flex-shrink: 0;
    background-color: var(--c-p-600);
    border-radius: var(--r-xs);
}

/* 体重：圆盘 + 底座横条（纵排） */
.quick__glyph--weight {
    flex-direction: column;
}

.quick__glyph--weight .quick__g--a {
    width: 16rpx;
    height: 16rpx;
    border-radius: var(--r-full);
}

.quick__glyph--weight .quick__g--b {
    width: 22rpx;
    height: 4rpx;
    margin-top: var(--sp-1);
}

/* 血压：两支不同高度的竖条（横排、底对齐） */
.quick__glyph--bp {
    align-items: flex-end;
}

.quick__glyph--bp .quick__g--a {
    width: 6rpx;
    height: 16rpx;
}

.quick__glyph--bp .quick__g--b {
    width: 6rpx;
    height: 24rpx;
    margin-left: var(--sp-2);
}

/* 饮水：竖椭圆（水滴简化形） */
.quick__glyph--water .quick__g--a {
    width: 14rpx;
    height: 27rpx;
    border-radius: var(--r-full);
}

.quick__glyph--water .quick__g--b {
    display: none;
}

/* 运动：斜向圆角条（角度属图标几何，不计入比例值判据） */
.quick__glyph--sport .quick__g--a {
    width: 26rpx;
    height: 7rpx;
    transform: rotate(-45deg);
}

.quick__glyph--sport .quick__g--b {
    display: none;
}

.quick__unit {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.quick__name {
    display: block;
    margin-top: var(--sp-4);
    font-size: var(--fs-h3);
    line-height: $lh-h3;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

/* 「记一笔」：行内次要操作（--fs-btn-m），热区按 --tap-min 收敛在卡片内部 */
.quick__cta {
    margin-top: var(--sp-4);
    height: var(--tap-min);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    border-radius: var(--r-sm);
    border: 1rpx solid var(--b-border);
    background-color: var(--s-card-sub);
}

.quick__cta-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--c-p-600);
    letter-spacing: 0;
}
</style>
