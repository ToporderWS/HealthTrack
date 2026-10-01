<template>
    <!--
      C-09 AppChipTabs（横向滚动标签；DESIGN.md §8.1 已登记）
      规格：横向滚动（`scroll-view scroll-x`）标签组；用途 = **8 类指标切换**（S3-3 用于 SC-10）。

      八态：default / pressed（按下）/ selected（选中 = 品牌浅底 + 品牌文字）
            disabled（不可点，如首屏加载中）
            loading · error · success · offline —— **N/A**（选择控件不承载请求与数据态）
            empty —— **N/A**：`options` 为空时**整体不渲染**。

      ★ 不使用 emoji、不引入图标库；颜色与间距全部走设计令牌。
      ★ 未使用 `scroll-into-view`（避免"选中项自动滚到可视区"这一类额外交互），
        仅提供原生横向滚动；8 项在窄屏下可手动横滑。
    -->
    <scroll-view v-if="options.length" class="chips" scroll-x :show-scrollbar="false">
        <view class="chips__track">
            <view
                v-for="item in options"
                :key="item.value"
                class="chips__chip"
                :class="{ 'chips__chip--on': isOn(item) }"
                :hover-class="hoverClass(item)"
                :hover-start-time="0"
                :hover-stay-time="80"
                @tap="pick(item)"
            >
                <text class="chips__text" :class="{ 'chips__text--on': isOn(item) }">{{ item.label }}</text>
            </view>
        </view>
    </scroll-view>
</template>

<script>
export default {
    name: 'AppChipTabs',
    props: {
        /** 当前选中值 */
        modelValue: { type: [String, Number], default: '' },
        /** 选项：`[{ value, label }]`（顺序即展示顺序） */
        options: { type: Array, default: function () { return [] } },
        /** 整组不可点 */
        disabled: { type: Boolean, default: false }
    },
    emits: ['update:modelValue', 'change'],
    methods: {
        isOn: function (item) {
            return String(item.value) === String(this.modelValue)
        },
        hoverClass: function (item) {
            if (this.disabled || this.isOn(item)) {
                return 'none'
            }
            return 'chips__chip--press'
        },
        pick: function (item) {
            if (this.disabled) {
                return
            }
            if (String(item.value) === String(this.modelValue)) {
                return
            }
            this.$emit('update:modelValue', item.value)
            this.$emit('change', item.value)
        }
    }
}
</script>

<style scoped lang="scss">
.chips {
    width: 100%;
    white-space: nowrap;
}

.chips__track {
    display: flex;
    flex-direction: row;
    align-items: center;
}

.chips__chip {
    flex-shrink: 0;
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-height: var(--tap-min);
    padding-left: var(--sp-5);
    padding-right: var(--sp-5);
    margin-right: var(--sp-3);
    border-radius: var(--r-full);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-border);
    transition: background-color var(--d-fast) var(--ease-std),
        transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

/* 选中：品牌浅底 + 品牌文字（与 C-08 同一视觉语言） */
.chips__chip--on {
    background-color: var(--s-brand-soft);
    border: 1rpx solid var(--c-p-200);
}

.chips__chip--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.chips__text {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-regular;
    color: var(--t-2);
    letter-spacing: 0;
    white-space: nowrap;
}

.chips__text--on {
    font-weight: $fw-medium;
    color: var(--c-p-600);
}
</style>
