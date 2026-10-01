<template>
    <!--
      C-29 AccountDangerZone（「我的」页危险区）
      规格（DESIGN.md §8.3）：**独立分组 + 明显视觉分隔**；退出登录（中性 + 普通确认）/
                                 注销账号（`--c-danger` + 终局图标 + 强确认）。

      依据：S1-C SC-18 ③「危险操作区（与上方列表**视觉分隔**）」；
            S1-C SC-18 ⑮ 两套确认弹窗（**普通确认 vs 强确认**，必须明显不同）；
            DESIGN.md §12「『清空数据』与『注销账号』**五维必须不同**：入口位置 / 颜色 /
            验证强度 / 后果文案 / 完成去向」。

      ★ 本组件**只负责视觉与点击出口**，业务口径（确认强度、文案、清态、跳转）一律由
        「我的」页决定 —— 这样危险操作的两套确认逻辑集中在页面一处，便于逐条验收。

      ★ 第五维「验证强度」在本组件的体现 = **视觉分层**：注销项带 `--c-danger` 与终局图标，
        退出项保持中性；真正的验证强度差异（普通确认 / 文本+密码强确认）由页面的两套弹窗承载。

      八态（DESIGN.md §8 规则，逐项说明）：
        default  → 两项均可点；
        pressed  → 行按压反馈（scale + opacity，走 §7.3 Token）；
        disabled → 置灰（离线时由页面传入；**点击仍派发事件**，由页面给「当前网络不可用」提示 ——
                   不能"点了没反应"，与 SC-12「新建目标」离线处置同一口径）；
        error / loading / success / empty → **N/A**：本组件无自身请求、无数据、无自证状态；
                   提交中的 loading 由页面的确认弹窗按钮承载；
        offline  → 见 disabled（同一处置：视觉置灰 + 页面拦截并提示）。
    -->
    <view class="adz">
        <!-- 与上方功能列表的**明显视觉分隔**（--section-gap 为唯一来源，不写裸间距） -->
        <view class="adz__sep"></view>

        <view class="adz__card">
            <!-- ① 退出登录（中性色；数据保留） -->
            <view
                class="adz__row"
                :class="{ 'adz__row--off': disabled }"
                hover-class="adz__row--press"
                :hover-start-time="0"
                :hover-stay-time="80"
                @tap="onLogout"
            >
                <text class="adz__label" :class="{ 'adz__label--off': disabled }">{{ logoutLabel }}</text>
            </view>

            <view class="adz__line"></view>

            <!-- ② 注销账号（危险色 + 终局图标；不可逆） -->
            <view
                class="adz__row"
                :class="{ 'adz__row--off': disabled }"
                hover-class="adz__row--press"
                :hover-start-time="0"
                :hover-stay-time="80"
                @tap="onClose"
            >
                <!-- 终局图标：纯 CSS 几何（圆圈 + 斜杠），**不使用 emoji**（DESIGN.md §12 禁令） -->
                <view class="adz__icon" :class="{ 'adz__icon--off': disabled }"></view>
                <text class="adz__label adz__label--danger" :class="{ 'adz__label--off': disabled }">
                    {{ closeLabel }}
                </text>
            </view>
        </view>

        <text v-if="hint" class="adz__hint">{{ hint }}</text>
    </view>
</template>

<script>
export default {
    name: 'AccountDangerZone',
    props: {
        /** 退出登录文案（由页面给定，与注销文案**逐字不同**） */
        logoutLabel: { type: String, default: '退出登录' },
        /** 注销账号文案 */
        closeLabel: { type: String, default: '注销账号' },
        /** 危险区下方的中性说明（可选；离线说明等） */
        hint: { type: String, default: '' },
        /** 置灰（离线时由页面传入；**不阻断点击**，由页面给明确提示） */
        disabled: { type: Boolean, default: false }
    },
    emits: ['logout', 'close'],
    methods: {
        onLogout: function () {
            this.$emit('logout')
        },
        onClose: function () {
            this.$emit('close')
        }
    }
}
</script>

<style scoped lang="scss">
.adz {
    width: 100%;
}

/* 明显视觉分隔：一整段留白（--section-gap 是与卡片间距不同量级的节奏值） */
.adz__sep {
    height: var(--section-gap);
}

.adz__card {
    border-radius: var(--r-md);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-line);
    overflow: hidden;
}

.adz__row {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-height: var(--tap-min);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.adz__row--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.adz__row--off {
    opacity: var(--press-opacity);
}

.adz__line {
    height: 1rpx;
    background-color: var(--b-line);
}

.adz__label {
    font-size: var(--fs-btn-l);
    line-height: $lh-btn-l;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.adz__label--danger {
    color: var(--c-danger);
}

.adz__label--off {
    color: var(--t-4);
}

/* 终局图标：圆圈轮廓 + 斜杠（图标边长按 §10.4 例外取 px，与 C-03 的眼睛同口径） */
.adz__icon {
    position: relative;
    width: 20px;
    height: 20px;
    margin-right: var(--sp-3);
    border: 2px solid var(--c-danger);
    border-radius: var(--r-full);
    flex-shrink: 0;
}

.adz__icon::before {
    content: '';
    position: absolute;
    left: 9px;
    top: 2px;
    width: 2px;
    height: 16px;
    background-color: var(--c-danger);
    transform: rotate(45deg);
}

.adz__icon--off {
    border: 2px solid var(--t-4);
}

.adz__icon--off::before {
    background-color: var(--t-4);
}

.adz__hint {
    display: block;
    margin-top: var(--sp-4);
    padding-left: var(--sp-2);
    padding-right: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
