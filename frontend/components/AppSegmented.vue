<template>
    <!--
      C-08 AppSegmented（顶部分段控件；DESIGN.md §8.1 已登记）
      规格：选中 = `--c-p-100` 底 + `--c-p-600` 文字；未选中 = 凹陷底 + 次要文字。
      用途（S3-3）：SC-10 记录历史列表的**时间范围**切换（近 7 天 / 近 30 天 / 近 90 天 / 自定义）。

      八态：default（可点）/ pressed（按下反馈）/ disabled（不可点，如加载中）
            loading · error · success · offline —— **N/A**
            （本组件是**纯选择控件**，不承载请求、不承载数据态；加载 / 失败 / 离线由宿主页的
              骨架屏 / 失败态 / 离线条承担，避免在分段控件上制造重复语义。）
            empty —— **N/A**：`options` 为空时**整体不渲染**（不出现空分段条）。

      ★ 不使用 emoji、不引入图标库；颜色与间距全部走设计令牌。
    -->
    <view v-if="options.length" class="seg" :class="{ 'seg--disabled': disabled }">
        <view
            v-for="item in options"
            :key="item.value"
            class="seg__item"
            :class="{ 'seg__item--on': isOn(item) }"
            :hover-class="hoverClass(item)"
            :hover-start-time="0"
            :hover-stay-time="80"
            @tap="pick(item)"
        >
            <text class="seg__text" :class="{ 'seg__text--on': isOn(item) }">{{ item.label }}</text>
        </view>
    </view>
</template>

<script>
export default {
    name: 'AppSegmented',
    props: {
        /** 当前选中值 */
        modelValue: { type: [String, Number], default: '' },
        /** 选项：`[{ value, label }]`（**顺序即展示顺序，组件不重排**） */
        options: { type: Array, default: function () { return [] } },
        /** 整组不可点（如首屏加载中） */
        disabled: { type: Boolean, default: false }
    },
    emits: ['update:modelValue', 'change'],
    methods: {
        isOn: function (item) {
            return String(item.value) === String(this.modelValue)
        },
        hoverClass: function (item) {
            if (this.disabled) {
                return 'none'
            }
            return 'seg__item--press'
        },
        /**
         * 选择一项。
         * ★ 如实登记（S3-3 实测需求）：**已选中项被再次点击时仍派发 `change`**
         *   （只是不再派发 `update:modelValue`）。
         *   原因：SC-10 的「自定义」不是纯枚举值，而是一个**开抽屉的动作** ——
         *   用户范围生效后再点「自定义」，需要重新打开抽屉修改范围；
         *   若此处因"值未变化"而静默 return，该入口会变成死点。
         *   对纯枚举宿主（如 SC-11 的 7/30/90 天）无副作用：重复值由宿主自行判重。
         */
        pick: function (item) {
            if (this.disabled) {
                return
            }
            if (String(item.value) === String(this.modelValue)) {
                this.$emit('change', item.value)
                return
            }
            this.$emit('update:modelValue', item.value)
            this.$emit('change', item.value)
        }
    }
}
</script>

<style scoped lang="scss">
.seg {
    display: flex;
    flex-direction: row;
    align-items: center;
    padding: var(--sp-1);
    border-radius: var(--r-md);
    background-color: var(--s-sunken);
}

.seg__item {
    flex: 1;
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-height: var(--tap-min);
    border-radius: var(--r-sm);
    transition: background-color var(--d-fast) var(--ease-std),
        transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

/* 选中：品牌浅底 + 品牌文字（DESIGN.md §8.1 C-08 规定） */
.seg__item--on {
    background-color: var(--c-p-100);
}

.seg__item--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.seg__text {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-regular;
    color: var(--t-2);
    letter-spacing: 0;
}

.seg__text--on {
    font-weight: $fw-medium;
    color: var(--c-p-600);
}

/* 整组禁用：用"次要文字色 + 凹陷底"表达，不用透明度（DESIGN.md §2.1） */
.seg--disabled {
    background-color: var(--s-sunken);
}

.seg--disabled .seg__text {
    color: var(--t-4);
}
</style>
