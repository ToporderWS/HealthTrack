<template>
    <!--
      C-20 AppListRow（列表行；DESIGN.md §8.2 已登记）
      规格：icon + title + subtitle + value + arrow / switch / action；高度 ≥ `--row-h`。
      用途（S3-3）：SC-09 记录详情页的**字段列表**（记录时间 / 专属字段 / 标签 / 备注 / 元信息）。

      八态：default / pressed（整行按下 → 底色 `--c-n-100`，`--d-row`）/ disabled（不可点）
            empty —— **N/A**：行内容由宿主页决定，空值不渲染本行（不出现空行）
            loading · error · success · offline —— **N/A**（本组件是展示行，不承载请求与数据态）

      ★ switch / action 变体的如实登记（**不预造无用 UI**）：
        `switch` 需要 C-19 `AppSwitch`，该组件**尚未实现**（属后续批次），且 S3-3 的
        SC-09 / SC-10 **没有任何开关型设置行** ⇒ 本批**不实现 switch 变体**（避免为一个
        无使用方的控件预造交互）；`action` 由宿主页经右侧 `value` 插槽承载。
        C-19 落地后如需本组件承载开关，再按同一契约补齐 —— 届时**不改变现有 props**。
    -->
    <view
        class="lrow"
        :class="{ 'lrow--last': last, 'lrow--disabled': disabled }"
        :hover-class="rowHoverClass"
        :hover-start-time="0"
        :hover-stay-time="80"
        @tap="handleTap"
    >
        <!-- 图标（可选）：纯 CSS 几何构成，与 C-21 / C-27 共用同一套图形语言 -->
        <view v-if="icon" class="lrow__icon">
            <view class="lrow__glyph" :class="'lrow__glyph--' + icon">
                <view class="lrow__g lrow__g--a"></view>
                <view class="lrow__g lrow__g--b"></view>
            </view>
        </view>

        <view class="lrow__body">
            <text v-if="title" class="lrow__title">{{ title }}</text>
            <text v-if="subtitle" class="lrow__subtitle">{{ subtitle }}</text>
            <slot></slot>
        </view>

        <view class="lrow__tail">
            <text v-if="value !== '' && value !== null && value !== undefined" class="lrow__value">{{ value }}</text>
            <!-- 指示箭头：纯 CSS 几何（旋转 45° 的两段边框），不引入图标库 -->
            <view v-if="arrow" class="lrow__chevron"></view>
            <slot name="tail"></slot>
        </view>
    </view>
</template>

<script>
export default {
    name: 'AppListRow',
    props: {
        /** 图标标识（8 类指标 type 之一；空 → 不渲染图标位） */
        icon: { type: String, default: '' },
        /** 主文案（左侧标题，如「测量时间」） */
        title: { type: String, default: '' },
        /** 次文案（标题下方小字，可为空） */
        subtitle: { type: String, default: '' },
        /** 右侧值（**已由宿主页格式化**；空串 → 不渲染值位） */
        value: { type: [String, Number], default: '' },
        /** 是否显示右箭头（表示"可点进下级"；无下级则保持 false，避免假入口） */
        arrow: { type: Boolean, default: false },
        /** 是否为最后一行（最后一行不画分隔线） */
        last: { type: Boolean, default: false },
        /** 不可点（用"次要文字色"表达，不用透明度） */
        disabled: { type: Boolean, default: false }
    },
    emits: ['tap'],
    computed: {
        tapEnabled: function () {
            return !this.disabled && this.arrow
        },
        rowHoverClass: function () {
            return this.tapEnabled ? 'lrow--press' : 'none'
        }
    },
    methods: {
        handleTap: function () {
            if (!this.tapEnabled) {
                return
            }
            this.$emit('tap')
        }
    }
}
</script>

<style scoped lang="scss">
.lrow {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--row-h);
    padding-top: var(--row-pad-y);
    padding-bottom: var(--row-pad-y);
    border-bottom: 1rpx solid var(--b-line);
    transition: background-color var(--d-row) var(--ease-std);
}

/* 列表行按下反馈：改底色（DESIGN.md §7①），不走 scale/opacity */
.lrow--press {
    background-color: var(--c-n-100);
}

.lrow--last {
    border-bottom: none;
}

/* ── 图标（圆底 + 1rpx 描边，与 C-21 / C-27 同构） ── */
.lrow__icon {
    width: 56rpx;
    height: 56rpx;
    margin-right: var(--sp-4);
    border-radius: var(--r-full);
    background-color: var(--s-card-sub);
    border: 1rpx solid var(--b-line);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

/* ── 图标画布（几何构成；只用 flex + 尺寸 + 令牌间距，**不使用绝对定位偏移**） ── */
.lrow__glyph {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    width: 30rpx;
    height: 30rpx;
}

.lrow__g {
    flex-shrink: 0;
    background-color: var(--c-p-600);
    border-radius: var(--r-xs);
}

/* 体重：圆盘 + 底座横条（纵排） */
.lrow__glyph--weight {
    flex-direction: column;
}

.lrow__glyph--weight .lrow__g--a {
    width: 15rpx;
    height: 15rpx;
    border-radius: var(--r-full);
}

.lrow__glyph--weight .lrow__g--b {
    width: 21rpx;
    height: 4rpx;
    margin-top: var(--sp-1);
}

/* 血压：两支不同高度的竖条（横排、底对齐） */
.lrow__glyph--bp {
    align-items: flex-end;
}

.lrow__glyph--bp .lrow__g--a {
    width: 6rpx;
    height: 15rpx;
}

.lrow__glyph--bp .lrow__g--b {
    width: 6rpx;
    height: 23rpx;
    margin-left: var(--sp-2);
}

/* 心率：脉冲点 + 竖直指示线（横排） */
.lrow__glyph--heart .lrow__g--a {
    width: 12rpx;
    height: 12rpx;
    border-radius: var(--r-full);
}

.lrow__glyph--heart .lrow__g--b {
    width: 4rpx;
    height: 21rpx;
    margin-left: var(--sp-2);
}

/* 血糖：单支竖圆条（试管外形） */
.lrow__glyph--glucose .lrow__g--a {
    width: 9rpx;
    height: 25rpx;
    border-radius: var(--r-full);
}

.lrow__glyph--glucose .lrow__g--b {
    display: none;
}

/* 睡眠：两条不同长度的横线（纵排、左对齐） */
.lrow__glyph--sleep {
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
}

.lrow__glyph--sleep .lrow__g--a {
    width: 23rpx;
    height: 5rpx;
}

.lrow__glyph--sleep .lrow__g--b {
    width: 13rpx;
    height: 5rpx;
    margin-top: var(--sp-1);
}

/* 饮水：竖椭圆（水滴简化形） */
.lrow__glyph--water .lrow__g--a {
    width: 13rpx;
    height: 25rpx;
    border-radius: var(--r-full);
}

.lrow__glyph--water .lrow__g--b {
    display: none;
}

/* 运动：斜向圆角条（角度属图标几何，不计入比例值判据） */
.lrow__glyph--sport .lrow__g--a {
    width: 25rpx;
    height: 7rpx;
    transform: rotate(-45deg);
}

.lrow__glyph--sport .lrow__g--b {
    display: none;
}

/* 心情：实心圆点 */
.lrow__glyph--mood .lrow__g--a {
    width: 19rpx;
    height: 19rpx;
    border-radius: var(--r-full);
}

.lrow__glyph--mood .lrow__g--b {
    display: none;
}

/* ── 主体 ── */
.lrow__body {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-width: 0;
}

.lrow__title {
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-regular;
    color: var(--t-2);
    letter-spacing: 0;
}

.lrow__subtitle {
    margin-top: var(--sp-1);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── 右侧 ── */
.lrow__tail {
    display: flex;
    flex-direction: row;
    align-items: center;
    flex-shrink: 0;
    margin-left: var(--sp-4);
}

.lrow__value {
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
    text-align: right;
}

/* 右箭头（图标边长按 DESIGN.md §10.4② 例外以 px 栅格对齐） */
.lrow__chevron {
    width: 8px;
    height: 8px;
    margin-left: var(--sp-2);
    border-right: 2px solid var(--t-3);
    border-bottom: 2px solid var(--t-3);
    transform: rotate(-45deg);
}

/* 禁用：次要文字色（不用透明度） */
.lrow--disabled .lrow__title,
.lrow--disabled .lrow__value {
    color: var(--t-4);
}
</style>
