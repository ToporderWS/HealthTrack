<template>
    <!--
      C-26 ProgressRing（进度环）
      规格：conic-gradient 实现；**品牌色进度 + `--c-n-100` 轨道**；size = s(80) / m(120) / l(160) rpx。

      八态：default（有进度）/ empty（percent = 0 → 仅显示轨道，属"尚无进度"的正常展示）
            pressed · disabled · loading · error · success · offline —— **N/A**（纯展示，无交互、无结果态）

      色值全部经 `var()` 引用 §2.2 / §2.1 令牌，组件内零裸色值。
      **进度百分比是数据**（来自 S-01 的 `progress_percent`），不是设计令牌，
      故以 inline style 注入梯度字符串；梯度中的颜色**仍为 var(--x) 引用**。
      图形**不表示健康好坏**（DESIGN.md §12）：进度高低只由数字与长度表达，不切换色相。
    -->
    <view class="ring" :class="'ring--' + size" :style="ringStyle">
        <view class="ring__hole">
            <slot></slot>
        </view>
    </view>
</template>

<script>
export default {
    name: 'ProgressRing',
    props: {
        /** 进度百分比（0–100；超界仅夹紧图形，不改变数据展示） */
        percent: { type: Number, default: 0 },
        size: { type: String, default: 'm' }
    },
    computed: {
        safePercent: function () {
            const n = Number(this.percent)
            if (isNaN(n) || n < 0) {
                return 0
            }
            return n > 100 ? 100 : n
        },
        ringStyle: function () {
            const p = this.safePercent
            return {
                background: 'conic-gradient(var(--c-p-600) 0 ' + p +
                    '%, var(--s-sunken) ' + p + '% 100%)'
            }
        }
    }
}
</script>

<style scoped lang="scss">
.ring {
    position: relative;
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    border-radius: var(--r-full);
}

/* 三档尺寸（DESIGN.md §8.3 C-26） */
.ring--s {
    width: 80rpx;
    height: 80rpx;
}

.ring--m {
    width: 120rpx;
    height: 120rpx;
}

.ring--l {
    width: 160rpx;
    height: 160rpx;
}

/* 中心镂空：底色取卡片表面令牌（本组件只在卡片内使用） */
.ring__hole {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    width: 72%;
    height: 72%;
    border-radius: var(--r-full);
    background-color: var(--s-card);
}
</style>
