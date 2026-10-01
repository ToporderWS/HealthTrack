<template>
    <!--
      C-15 AppSkeleton（G2 加载）
      规格：list / card / chart / profile 四种骨架；仅**透明度呼吸** `--d-breathe`，不做扫光位移（DESIGN.md §7④）。
      八态：default（骨架显示中）/ loading（即本态）/ pressed·disabled·error·success·empty·offline —— **N/A**（纯占位）。
      本批实际使用：`profile`（SC-05 读取档案时）。list / card / chart 三种变体留待 S3-2 起按需启用。
    -->
    <view class="skeleton">
        <template v-if="variant === 'profile'">
            <view class="skeleton__row" v-for="n in 3" :key="'p' + n">
                <view class="skeleton__label"></view>
                <view class="skeleton__value"></view>
            </view>
        </template>

        <template v-else-if="variant === 'list'">
            <view class="skeleton__list-item" v-for="n in 4" :key="'l' + n">
                <view class="skeleton__avatar"></view>
                <view class="skeleton__lines">
                    <view class="skeleton__line skeleton__line--wide"></view>
                    <view class="skeleton__line"></view>
                </view>
            </view>
        </template>

        <template v-else-if="variant === 'chart'">
            <view class="skeleton__chart">
                <view class="skeleton__bar" v-for="n in 6" :key="'c' + n" :style="{ height: barHeight(n) }"></view>
            </view>
        </template>

        <template v-else>
            <view class="skeleton__card">
                <view class="skeleton__line skeleton__line--wide"></view>
                <view class="skeleton__line"></view>
                <view class="skeleton__line skeleton__line--short"></view>
            </view>
        </template>
    </view>
</template>

<script>
export default {
    name: 'AppSkeleton',
    props: {
        variant: { type: String, default: 'profile' }
    },
    methods: {
        barHeight: function (index) {
            // 骨架柱高仅作占位等高示意（非真实数据、非设计令牌）
            const ratios = [40, 62, 30, 74, 52, 46]
            return ratios[(index - 1) % ratios.length] + '%'
        }
    }
}
</script>

<style scoped lang="scss">
.skeleton {
    width: 100%;
    animation: skeleton-breathe var(--d-breathe) var(--ease-std) infinite;
}

.skeleton__row {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    padding: var(--sp-4) 0;
}

.skeleton__label {
    width: 25%;
    height: 24rpx;
    border-radius: var(--r-xs);
    background-color: var(--s-sunken);
}

.skeleton__value {
    width: 40%;
    height: 24rpx;
    border-radius: var(--r-xs);
    background-color: var(--s-sunken);
}

.skeleton__list-item {
    display: flex;
    flex-direction: row;
    align-items: center;
    padding: var(--sp-4) 0;
}

.skeleton__avatar {
    width: 64rpx;
    height: 64rpx;
    border-radius: var(--r-full);
    background-color: var(--s-sunken);
    margin-right: var(--sp-5);
}

.skeleton__lines {
    flex: 1;
}

.skeleton__line {
    height: 24rpx;
    border-radius: var(--r-xs);
    background-color: var(--s-sunken);
    margin-bottom: var(--sp-3);
    width: 60%;
}

.skeleton__line--wide {
    width: 100%;
}

.skeleton__line--short {
    width: 35%;
}

.skeleton__chart {
    display: flex;
    flex-direction: row;
    align-items: flex-end;
    justify-content: space-between;
    height: 240rpx;
}

.skeleton__bar {
    width: 12%;
    border-radius: var(--r-xs);
    background-color: var(--s-sunken);
}

.skeleton__card {
    padding: var(--card-pad);
    border-radius: var(--r-md);
    border: 1rpx solid var(--b-line);
    background-color: var(--s-card);
}

/* 仅透明度呼吸（不做扫光位移） */
@keyframes skeleton-breathe {
    0% {
        opacity: 1;
    }
    50% {
        /* 最低不透明度取自 §7③ Token，不在组件内出现裸比例值 */
        opacity: var(--breathe-opacity);
    }
    100% {
        opacity: 1;
    }
}
</style>
