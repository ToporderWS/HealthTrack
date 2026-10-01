<template>
    <!--
      SC-02 首次引导页（pages/onboarding/index）
      依据：S1-C §二 SC-02 ｜ DESIGN.md §11 / §12
      · ① 轮播 3 屏 ② 页码点（可点 / 可滑） ③ 主按钮「下一步」→ 第 3 屏「开始使用」
        ④ 次按钮「跳过」→ 直接到第 3 屏（**不跳过协议**） ⑤ 协议弹窗（勾选后方可继续）
      · 第 3 屏与协议弹窗均含**非医疗器械声明**
      · 纯本地：引导完成与协议同意标记写本地存储（**不写任何敏感信息**，无网络请求）
      · 状态覆盖：正常 / 首次使用（本页即首次使用态）/ 未勾选协议 / 拒绝 / 离线（全可离线完成）
        / loading·失败·未登录·高风险：N/A（无请求、对访客开放、非危险操作）
    -->
    <view class="guide">
        <!--
          ⚠️ 硬约束（2026-09-17 运行期缺陷修复）：**不得删除下面三处 :key，也不得把三屏改回 v-for。**
          根因（已用运行时取证 + 编译产物对照逐条验证，非推断）：
            HBuilderX 内置的 @dcloudio/uni-h5-vue 是旧版 Vue3 分支（3.0.0-5020420260812001）：
            · initSlots() 把 instance.slots 直接指向编译期 slot 对象本体，并 def(children, "_") 将 "_"
              定义为**不可写**；updateSlots() 在 optimized === false 时对同一对象执行
              Object.assign(slots, children) ⇒ 等于给自己只读键 "_" 赋值 ⇒
              TypeError: Cannot assign to read only property '_'（Vue 报
              Unhandled error during execution of scheduler flush），该组件本次更新整体中止。
            · optimized 是**挂载时**捕获的闭包值（updateComponentPreRender(instance, next, optimized)
              用的就是它）；uni-h5 的 view / text / swiper 等内置组件在 setup() 里以 createVNode() 渲染，
              其子节点一律以 optimized = false 挂载 ⇒ 本页所有「带子节点的 <view>/<swiper>/<AppModal>」
              都恒为 false。**因此加 :key 让 vnode 变成 block 也救不了（挂载值仍是 false，已实测）。**
            · 结论：这类组件只要 **props 发生变化（含 class）** 就会抛错 ⇒ 唯一解是「不让它走更新路径」：
              给它一个**随变化值而变的 :key**，使其走重挂载（重挂载走 initSlots，不经过 updateSlots）。
          （官方 Vue 3.5 已修复：assignSlots() 跳过 "_" 等内部键，initSlots 用 def(..., true) 置为可写；
            运行时位于 HBuilderX 安装目录内，项目侧不能改，只能规避。）
          三处规避（缺一不可）：
            ① 轮播 :key="swiperKey"（随 current 变）—— 换屏＝重挂载，顺带规避 <swiper-item> 被 patch；
               uni-swiper 的 state.current 初值即 props.current ⇒ 重挂载后直接落在目标屏。
            ② 协议弹窗 :key="showAgreement ? 'agreement-open' : 'agreement-closed'"（随 show 变）——
               开与关都是重挂载，永不触发「props 变化 → updateSlots」；内容由 AppModal 自身渲染副作用重绘。
            ③ 勾选框 :key="checked ? 'abox-on' : 'abox-off'"（随 checked 变）—— 选中态的 class 变化同样
               必须走重挂载，否则勾选后无高亮/无勾号（已实测）。
          附：不带子节点的组件（如 C-01 AppButton）与 ARRAY_CHILDREN 的组件天然安全，无需 :key。
          三屏为 SC-02 冻结设计；文案单一来源于 data.slides；插画形状按屏固定
          （1 = 记录卡 / 2 = 柱状 / 3 = 进度环），与 data.slides[n].art 取值一一对应。
        -->
        <swiper
            :key="swiperKey"
            class="guide__swiper"
            :current="current"
            :duration="swiperDuration"
            :indicator-dots="false"
            :circular="false"
            @change="handleSwiperChange"
        >
            <swiper-item>
                <view class="slide">
                    <!-- 抽象插画位：纯 CSS 几何构成（不引入插图库） -->
                    <view class="slide__art" :class="'slide__art--' + slides[0].art">
                        <view class="art-card">
                            <view class="art-line art-line--wide"></view>
                            <view class="art-line"></view>
                            <view class="art-line art-line--short"></view>
                        </view>
                    </view>

                    <text class="slide__title">{{ slides[0].title }}</text>
                    <text class="slide__desc">{{ slides[0].desc }}</text>
                </view>
            </swiper-item>

            <swiper-item>
                <view class="slide">
                    <view class="slide__art" :class="'slide__art--' + slides[1].art">
                        <view class="art-bars">
                            <view class="art-bar art-bar--1"></view>
                            <view class="art-bar art-bar--2"></view>
                            <view class="art-bar art-bar--3"></view>
                            <view class="art-bar art-bar--4"></view>
                        </view>
                    </view>

                    <text class="slide__title">{{ slides[1].title }}</text>
                    <text class="slide__desc">{{ slides[1].desc }}</text>
                </view>
            </swiper-item>

            <swiper-item>
                <view class="slide">
                    <view class="slide__art" :class="'slide__art--' + slides[2].art">
                        <view class="art-ring">
                            <view class="art-ring__hole"></view>
                        </view>
                    </view>

                    <text class="slide__title">{{ slides[2].title }}</text>
                    <text class="slide__desc">{{ slides[2].desc }}</text>

                    <view class="slide__notice">
                        <text class="slide__notice-text">{{ deviceNotice }}</text>
                    </view>
                </view>
            </swiper-item>
        </swiper>

        <!-- 页码点：可点击跳屏；点击热区 ≥ var(--tap-min) -->
        <view class="guide__dots">
            <view
                v-for="(slide, index) in slides"
                :key="'dot' + index"
                class="guide__dot-hit"
                @tap="goSlide(index)"
            >
                <view class="guide__dot" :class="{ 'guide__dot--active': index === current }"></view>
            </view>
        </view>

        <view class="guide__actions">
            <AppButton
                :label="isLastSlide ? '开始使用' : '下一步'"
                type="primary"
                size="l"
                block
                @tap="handlePrimary"
            />
            <view v-if="!isLastSlide" class="guide__skip" hover-class="guide__skip--press" @tap="handleSkip">
                <text class="guide__skip-text">跳过</text>
            </view>
        </view>

        <!-- 协议弹窗：G7 变体（非危险色）；勾选框真实可交互 -->
        <AppModal
            :key="showAgreement ? 'agreement-open' : 'agreement-closed'"
            v-model:show="showAgreement"
            mode="info"
            title="用户协议与隐私政策"
            confirm-text="同意并继续"
            cancel-text="拒绝"
            @confirm="handleAgree"
            @cancel="handleReject"
        >
            <view class="agreement">
                <text class="agreement__text" v-for="(line, index) in agreementLines" :key="index">{{ line }}</text>

                <view class="agreement__notice">
                    <text class="agreement__notice-text">{{ deviceNotice }}</text>
                </view>

                <text class="agreement__draft">（技术实现草案 · 上线前需经法律/合规审核）</text>

                <view class="agreement__check" @tap="toggleChecked">
                    <view
                        :key="checked ? 'abox-on' : 'abox-off'"
                        class="agreement__box"
                        :class="{ 'agreement__box--checked': checked }"
                    >
                        <view v-if="checked" class="agreement__tick"></view>
                    </view>
                    <text class="agreement__check-text">我已阅读并同意《用户协议》与《隐私政策》</text>
                </view>

                <!-- S4-1：进入完整协议页（SC-24 / SC-23 对访客放行；返回后本弹窗与勾选状态保持）。
                     本块为**纯静态内容**（无 hover-class、无动态 class 绑定）—— 本弹窗历史上受
                     HBuilderX 内置旧版 uni-h5-vue 的 updateSlots 缺陷影响，故刻意不引入任何会让
                     自身重渲染的绑定，保持与既有规避策略一致。 -->
                <view class="agreement__links">
                    <view class="agreement__link" @tap="openTerms">
                        <text class="agreement__link-text">查看完整《用户协议》</text>
                    </view>
                    <view class="agreement__link" @tap="openPrivacy">
                        <text class="agreement__link-text">查看完整《隐私政策》</text>
                    </view>
                </view>
            </view>
        </AppModal>

        <AppToast />
    </view>
</template>

<script>
import AppButton from '../../components/AppButton.vue'
import AppModal from '../../components/AppModal.vue'
import AppToast from '../../components/AppToast.vue'
import { showToast } from '../../utils/toast'
import { saveAgreement } from '../../utils/auth'
import { AGREEMENT_VERSION } from '../../utils/config'
import { ROUTES, navigateTo } from '../../utils/route'

/** 非医疗器械声明（S1-C SC-02 / SC-25 口径） */
const DEVICE_NOTICE = '本应用为个人健康记录与趋势查看工具，不是医疗器械，不提供疾病诊断、病情判断、医学结论或用药建议。'

/** 轮播切换时长 = 设计令牌 `--d-slow`（300ms，§7 上限）；uni 默认 500ms 超上限，故显式指定 */
const SWIPER_DURATION_MS = 300

export default {
    components: {
        AppButton: AppButton,
        AppModal: AppModal,
        AppToast: AppToast
    },
    data: function () {
        return {
            current: 0,
            showAgreement: false,
            checked: false,
            swiperDuration: SWIPER_DURATION_MS,
            deviceNotice: DEVICE_NOTICE,
            slides: [
                {
                    art: 'record',
                    title: '记录健康数据',
                    desc: '体重、血压、心率、血糖、睡眠、饮水、运动、情绪，随手记一笔。'
                },
                {
                    art: 'trend',
                    title: '看长期趋势',
                    desc: '按 7 天 / 30 天 / 90 天查看变化，只呈现你自己记录的数据。'
                },
                {
                    art: 'goal',
                    title: '设目标与提醒',
                    desc: '给自己定一个目标，按自己的节奏推进。'
                }
            ],
            agreementLines: [
                '本应用仅用于记录你主动填写的个人健康数据，并展示这些数据随时间的变化。',
                '数据仅归属于你的账号，不向第三方提供。',
                '你可以随时导出或删除自己的数据；注销账号后，相关数据将立即删除。',
                '本应用不提供任何医学判断、诊断结论或用药建议。'
            ]
        }
    },
    computed: {
        isLastSlide: function () {
            return this.current === this.slides.length - 1
        },
        /**
         * 轮播实例 key（见模板顶部硬约束说明）。
         * 变化的目的是让 <swiper> 走「重挂载」而非「更新实例」，
         * 以规避 HBuilderX 内置旧版 uni-h5-vue 的 updateSlots() 缺陷。
         */
        swiperKey: function () {
            return 'guide-swiper-' + this.current
        }
    },
    methods: {
        handleSwiperChange: function (event) {
            this.current = event && event.detail ? event.detail.current : this.current
        },
        goSlide: function (index) {
            this.current = index
        },
        handleSkip: function () {
            // 跳过 → 直接到第 3 屏（**不跳过协议**）
            this.current = this.slides.length - 1
        },
        handlePrimary: function () {
            if (this.isLastSlide) {
                this.checked = false
                this.showAgreement = true
                return
            }
            this.current = this.current + 1
        },
        toggleChecked: function () {
            this.checked = !this.checked
        },
        handleAgree: function () {
            if (!this.checked) {
                // 未勾选 → 不可继续（F-008 强制勾选）
                showToast('error', '请先阅读并同意用户协议与隐私政策')
                return
            }
            this.showAgreement = false
            // 本地留痕（设备级标记，不随登出清除；**不含任何敏感信息**）
            saveAgreement(AGREEMENT_VERSION, new Date().toString())
            // 同意 → SC-04 注册页（S1-C SC-02 ⑦）
            uni.reLaunch({ url: ROUTES.REGISTER })
        },
        handleReject: function () {
            this.showAgreement = false
            showToast('info', '不同意将无法使用本应用')
        },

        /**
         * S4-1：查看完整《用户协议》（SC-24）。
         * `navigateTo` 保留本页实例 => 返回后协议弹窗与已勾选状态**原样保留**，
         * 既不重置流程，也不重复征求同意（同意语义完全不变）。
         */
        openTerms: function () {
            navigateTo(ROUTES.TERMS)
        },

        /** S4-1：查看完整《隐私政策》（SC-23）；返回行为同上 */
        openPrivacy: function () {
            navigateTo(ROUTES.PRIVACY)
        }
    }
}
</script>

<style scoped lang="scss">
.guide {
    display: flex;
    flex-direction: column;
    height: 100vh;
    background-color: var(--s-page);
}

.guide__swiper {
    flex: 1;
    width: 100%;
}

.slide {
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding-top: calc(var(--status-bar-height) + var(--section-gap));
    padding-left: var(--sp-9);
    padding-right: var(--sp-9);
}

/* ── 插画位（几何构成） ── */
.slide__art {
    width: 320rpx;
    height: 320rpx;
    border-radius: var(--r-xl);
    background-color: var(--s-brand-soft);
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: var(--sp-9);
}

.art-card {
    width: 200rpx;
    padding: var(--sp-6) var(--sp-5);
    border-radius: var(--r-md);
    background-color: var(--s-card);
    box-shadow: var(--el-1);
}

.art-line {
    height: 14rpx;
    border-radius: var(--r-xs);
    background-color: var(--c-p-200);
    margin-bottom: var(--sp-4);
    width: 70%;
}

.art-line--wide {
    width: 100%;
}

.art-line--short {
    width: 45%;
    margin-bottom: 0;
}

.art-bars {
    display: flex;
    flex-direction: row;
    align-items: flex-end;
    height: 190rpx;
}

.art-bar {
    width: 28rpx;
    border-radius: var(--r-xs);
    background-color: var(--c-p-400);
    margin-left: var(--sp-2);
    margin-right: var(--sp-2);
}

.art-bar--1 {
    height: 50rpx;
}

.art-bar--2 {
    height: 92rpx;
}

.art-bar--3 {
    height: 70rpx;
}

.art-bar--4 {
    height: 140rpx;
    background-color: var(--c-p-600);
}

/* 目标进度环：环形轮廓 + 一段品牌色弧 */
.art-ring {
    width: 180rpx;
    height: 180rpx;
    border-radius: var(--r-full);
    border: 20rpx solid var(--c-p-100);
    border-top-color: var(--c-p-600);
    border-right-color: var(--c-p-600);
    display: flex;
    align-items: center;
    justify-content: center;
}

.art-ring__hole {
    width: 60rpx;
    height: 60rpx;
    border-radius: var(--r-full);
    background-color: var(--s-card);
}

.slide__title {
    font-size: var(--fs-h1);
    line-height: $lh-h1;
    font-weight: $fw-semibold;
    color: var(--t-1);
    text-align: center;
    letter-spacing: 0;
}

.slide__desc {
    margin-top: var(--sp-5);
    font-size: var(--fs-body);
    line-height: $lh-reading;
    color: var(--t-2);
    text-align: center;
    letter-spacing: 0;
}

.slide__notice {
    margin-top: var(--sp-8);
    padding: var(--sp-4) var(--sp-5);
    border-radius: var(--r-sm);
    background-color: var(--s-card-sub);
}

.slide__notice-text {
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    color: var(--t-3);
    text-align: center;
    letter-spacing: 0;
}

/* ── 页码点 ── */
.guide__dots {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
}

.guide__dot-hit {
    width: var(--tap-min);
    height: var(--tap-min);
    display: flex;
    align-items: center;
    justify-content: center;
}

.guide__dot {
    width: var(--sp-3);
    height: var(--sp-3);
    border-radius: var(--r-full);
    background-color: var(--c-n-300);
    transition: background-color var(--d-base) var(--ease-std), width var(--d-base) var(--ease-std);
}

/* 选中态用「拉长成胶囊 + 主色」表达，不使用任何裸比例值（§7③ 只登记按下反馈比例） */
.guide__dot--active {
    width: var(--sp-5);
    background-color: var(--c-p-600);
}

/* ── 操作区 ── */
.guide__actions {
    padding: 0 var(--gutter) calc(var(--safe-b) + var(--sp-8)) var(--gutter);
    display: flex;
    flex-direction: column;
    align-items: center;
}

.guide__skip {
    margin-top: var(--sp-4);
    min-height: var(--tap-min);
    padding-left: var(--sp-8);
    padding-right: var(--sp-8);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.guide__skip--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.guide__skip-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── 协议弹窗内容 ── */
.agreement__text {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-reading;
    color: var(--t-2);
    letter-spacing: 0;
    margin-bottom: var(--sp-3);
}

.agreement__notice {
    margin-top: var(--sp-4);
    padding: var(--sp-4) var(--sp-5);
    border-radius: var(--r-sm);
    background-color: var(--s-card-sub);
}

.agreement__notice-text {
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    color: var(--t-3);
    letter-spacing: 0;
}

.agreement__draft {
    display: block;
    margin-top: var(--sp-3);
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    color: var(--t-4);
    letter-spacing: 0;
}

/* 勾选行：整行可点，高度 ≥ var(--tap-min) */
.agreement__check {
    margin-top: var(--sp-5);
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--tap-min);
}

.agreement__box {
    width: 40rpx;
    height: 40rpx;
    border-radius: var(--r-xs);
    border: 1rpx solid var(--b-border);
    background-color: var(--s-card);
    display: flex;
    align-items: center;
    justify-content: center;
    margin-right: var(--sp-4);
    transition: background-color var(--d-fast) var(--ease-std), border-color var(--d-fast) var(--ease-std);
}

.agreement__box--checked {
    background-color: var(--c-p-600);
    border: 1rpx solid var(--c-p-600);
}

.agreement__tick {
    width: 8px;
    height: 14px;
    border-right: 2px solid var(--t-inverse);
    border-bottom: 2px solid var(--t-inverse);
    transform: rotate(45deg) translateY(-2rpx);
}

.agreement__check-text {
    flex: 1;
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

/* ── S4-1：完整协议入口（弹窗内） ──
   静态样式，**不设 pressed 态**（本弹窗内容区历史上受旧版 uni-h5-vue 的 updateSlots 缺陷影响，
   故不引入 hover-class）；热区高度仍 >= var(--tap-min)。 */
.agreement__links {
    margin-top: var(--sp-3);
    display: flex;
    flex-direction: column;
}

.agreement__link {
    min-height: var(--tap-min);
    display: flex;
    align-items: center;
}

.agreement__link-text {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-medium;
    color: var(--t-link);
    letter-spacing: 0;
}
</style>
