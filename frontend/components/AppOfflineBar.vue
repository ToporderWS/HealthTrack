<template>
    <!--
      C-17 AppOfflineBar（G5 离线标记条）/ AppNetworkBanner（G4 网络横幅）
      规格（DESIGN.md §8.2）：
        · 离线条 =「离线数据 · 更新于 <时间>」；
        · 网络横幅 = 离线 / 恢复两种瞬时提示（3 秒后由**页面**撤下，组件自身不做计时）。

      八态：offline（variant = offline，即本态）/ success（variant = restored，网络恢复）
            default · pressed · disabled · loading · error · empty —— **N/A**（非交互、无数据语义）

      语义色用途（DESIGN.md §2.3）：`--c-info` = 离线标记 / 状态说明；
      `--c-success` = **仅系统反馈**（网络已恢复属系统状态反馈，不涉及健康数据好坏）。
    -->
    <view class="bar" :class="'bar--' + variant">
        <view class="bar__mark"></view>
        <text class="bar__text">{{ text }}</text>
    </view>
</template>

<script>
export default {
    name: 'AppOfflineBar',
    props: {
        /** offline = 离线只读标记；restored = 网络恢复横幅 */
        variant: { type: String, default: 'offline' },
        /** 文案（离线条须为「离线数据 · 更新于 <时间>」，由页面拼装） */
        text: { type: String, default: '' }
    }
}
</script>

<style scoped lang="scss">
.bar {
    display: flex;
    flex-direction: row;
    align-items: center;
    padding: var(--sp-4) var(--sp-5);
    border-radius: var(--r-sm);
}

.bar--offline {
    background-color: var(--c-info-bg);
}

.bar--restored {
    background-color: var(--c-success-bg);
}

/* 几何标记：小方点（不使用 emoji、不使用图标库） */
.bar__mark {
    width: 12rpx;
    height: 12rpx;
    border-radius: var(--r-full);
    margin-right: var(--sp-3);
    flex-shrink: 0;
}

.bar--offline .bar__mark {
    background-color: var(--c-info);
}

.bar--restored .bar__mark {
    background-color: var(--c-success);
}

.bar__text {
    flex: 1;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    letter-spacing: 0;
}

.bar--offline .bar__text {
    color: var(--c-info);
}

.bar--restored .bar__text {
    color: var(--c-success);
}
</style>
