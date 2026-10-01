<template>
    <!--
      SC-18 我的页（pages/mine/index）  tabBar ④
      依据：S1-C §二 SC-18 ｜ DESIGN.md §8.2（C-20）/ §8.3（C-29）/ §10.3 / §11 / §12 / §13

      顶栏：**B 类自绘顶栏**（`DESIGN.md §10.3` 的 custom 名单逐字为
            SC-01 / 02 / 03 / 04 / 05 / 06 / 11 / **SC-18**）⇒ 本页使用 C-10 `AppNavBar`，
            并在 `pages.json` 声明 `navigationStyle: "custom"`（与 S3-7 注册同步落地）。
            这是本批**唯一**加 custom 的新页；SC-16 / SC-17 / SC-19 均为 A 类系统导航栏。

      结构（与 S1-C SC-18 逐项对应）：
        [① 个人资料区] 用户名（F-064，账号显示为用户名）+ 昵称（昵称属档案 F-060）；
                       两行共用**同一结构**「左字段名 + 右值 + 箭头」，整行点击 → SC-17
        [② 功能列表]   8 项：修改密码 → SC-19 / 健康档案 → SC-16 / 健康目标 → SC-12 /
                       健康提醒 → SC-14 / 数据管理 → SC-20 / 隐私政策 → SC-23 /
                       用户协议 → SC-24 / 关于 → SC-25
        [③ 危险操作区] 与上方列表**视觉分隔**（C-29）：退出登录（中性色）· 注销账号（危险色 + 终局图标）
        [⑦ 底部]       tabBar（C-11，4 项不得增删），`current: 'mine'`

      数据来源：`A-06 GET /users/me`（用户名 / 建档标记）+ `P-01 GET /profile`（昵称）。
        用户名**优先取本地已缓存值**（`store.user.username`）⇒ 离线时资料区仍可查看（S1-C ⑭）。

      状态覆盖（DESIGN.md §13 底线清单，逐项说明）：
        正常   ✅ 资料与列表正常展示；
        空     ✅ 昵称为空 → 资料区显示「未设置昵称」（次要文字色）；**列表项恒在，无整页空状态**（S1-C ⑩）；
        加载   ✅ **仅资料区骨架**，功能列表与危险区**立即可用**（S1-C ⑪）；
        失败   ✅ 资料区显示 `AppErrorState` 占位 + 重试；**列表入口不受影响**（S1-C ⑫）；
        未登录 ✅ 路由守卫 → SC-03（S1-C ⑬）；
        离线   ✅ 页面可查看（本地已有信息）；退出登录 / 注销账号为**写操作** ⇒ 危险区置灰，
                 点击后由本页明确提示「当前网络不可用，请联网后操作」（不"点了没反应"，S1-C ⑭）；
        401    → 由统一请求层处理（单次 Refresh → 重放；失败清栈回 SC-03）；
        提交防重 ✅ 弹层确认按钮立即 `confirm-disabled` + 提交中不重复派发（F-083 第一道防线）；
        高风险确认 ✅ **两套强度不同的弹层**（见下）。

      ⑮ 两套确认（**必须明显不同**，S1-C SC-18 ⑮ 原文）
        ① 退出登录：普通确认（中性色）「退出后需重新登录」+「你的数据会保留在账号中，重新登录即可恢复」
                    + 说明会一并清除本地缓存与取消已注册的系统提醒通知；按钮 [取消] [退出]。
        ② 注销账号：**强确认（danger：红色 + 后果清单 + 文本输入 + 密码输入）**，标题「注销账号」+
                    后果清单 + 「此操作不可撤销，账号将无法恢复，且无等待期」；
                    需输入文本「注销账号」+ 登录密码；按钮 [取消] [确认注销]。

      ★ 第五维「数据下场表述」的逐字区分（`DESIGN.md §12` 五维必须不同）
        退出：**「你的数据会保留在账号中」**（仅结束当前会话）；
        注销：**「将按隐私政策及法律法规删除或匿名化」**（终局）。
        ⇒ **不得**把注销说成「清空数据」；**不得**出现「30 天」「冷静期」「撤销注销」（R-13 无静默期）。

      ★ S4-1 状态更新（2026-09-22）：后 3 项已**解灰并接线**（如实登记，非"历史漏做"）
        ① 隐私政策 SC-23 / 用户协议 SC-24 / 关于 SC-25 三页随 **S4-1「V1.0 完整化与发布前功能补齐」**
           落地：`pages.json` 22 -> **25**（恢复冻结 25 页口径，**非**新增第 26 页）；
           `utils/route.js` 新增 `PRIVACY` / `TERMS` / `ABOUT`；本页 3 项 `enabled` 改 `true`，
           并在 `onFunc` 补 3 条分支。
        （历史沿革：这三页在 S3-2~S3-9 分批表中无批次归属（预检 G-7）⇒ 当时按 B-1 推荐值 A
           "列表项恒在但置灰不可点"，**不产生死链接、不渲染假页面**；S3-8 子项 3.4 已按同一预留口子
           先行落地「数据管理」（19 -> 22 页）。S4-1 沿用该口子把剩余 3 项接通，**结构未变**。）
        ② **本页无「设置」入口、无「意见反馈」入口**（`S1-C §附 P1 表`：F-068 属 V1.1）。
        ③ `A-04` 退出登录失败（非 401）时：**不跳转、不清态**，只提示错误（S1-C ⑯「失败 → 明确提示 + 不跳转」）。
           服务端会话未失效即视为未退出，避免本地与服务端不一致。
        ④ 「取消已注册的系统提醒通知」在 **H5 恒为空操作**（真机能力留 S3-9）；
           本页只负责调用 `store.clearSessionAndCache()`，其内部**先** `cancelAllRegistered()`
           再删键（I-01 的实现通道，S3-5 已就绪）⇒ 本页**零改动**满足 I-01。
        ⑤ **规格偏差登记（2026-09-18 需求方指示的视觉优化，本批未改任何冻结文档）**：
           S1-C SC-18 ⑩ 字面为「显示『未设置昵称』+「去设置」」，原型图另有「[编辑昵称] → SC-17」；
           需求方本轮明确要求昵称行改为「字段名 + 右侧值 + 箭头」统一结构，且
           **「去设置」/「编辑昵称」不得与「昵称值」挤在同一行**。
           ⇒ 处理：「未设置昵称」**保留**；字面「去设置」/「编辑昵称」**不再作为同行文字动作渲染**，
           其「提供设置入口」的语义**改由「整行可点 + 右箭头」承载**，出口仍为 SC-17，功能逻辑不变。
           **S1-C / `DESIGN.md` 零改动**，仅在此登记，供需求方裁定是否回写规格。

      ★ B4-2 第二批（2026-09-29）：① 个人资料区新增「邮箱」行（资料区第 3 行）。
        展示值**只消费 A-06** 的 `email_bound` / `email_masked`（未绑定 ⇒「未绑定」+ 操作「绑定」；
        已绑定 ⇒ 后端掩码 + 操作「更换」）；整行点击 → 页内 `AppModal` 承载 `EmailBindPanel`。
        成功出口 ＝ 关闭弹层 + `refreshProfile(true)` 重取 A-06（**A-06 是最终显示权威**；
        父页面**不**伪造 `email_masked`、**不**改 store、**不**假设绑定成功）。
        **未新增页面 / 新增组件 / 新增依赖**（25 页口径不变；`store/user.js` 零改动）。
    -->
    <view class="mine">
        <!-- ① 顶部栏（B 类自绘顶栏；无返回 —— 本页是 tabBar 一级页） -->
        <AppNavBar title="我的" />

        <view class="mine__body">
            <view class="mine__inner">
                <!-- 离线标记（页面可查看；退出 / 注销为写操作 ⇒ 危险区置灰并拦截） -->
                <view v-if="offline" class="mine__notice">
                    <AppOfflineBar variant="offline" text="当前离线，退出登录与注销账号需联网后操作" />
                </view>

                <!-- 网络恢复横幅（3s 后自行撤下，DESIGN.md §8.2 C-17） -->
                <view v-if="restoredVisible" class="mine__notice">
                    <AppOfflineBar variant="restored" text="网络已恢复" />
                </view>

                <!-- ① 个人资料区（F-064） -->
                <AppCard title="个人资料" class="mine__block">
                    <!--
                      ★ S4-2C 头像区（**S4-2A §十 冻结结构**：头像区位于 `profileRows` 之上）

                      为什么放在「卡片内、资料行之上」且**在加载 / 失败两个分支之外**：
                        ① 位置与 S4-2A §十 的冻结结构一致；
                        ② 资料区骨架或失败占位出现时头像位不跳变，且「点击头像」入口在
                           离线 / 失败态下依然可达（离线时点击给离线提示，见 `onAvatarTap`）。

                      ★ 实现硬约束（S4-2A §十 第 1 条，源自 HBuilderX 内置旧版 `uni-h5-vue`
                        的 `updateSlots()` 缺陷）：新增块容器**只用静态 class**、
                        **不使用 `hover-class`**；`<image>` 上的 `:src` 属**叶子节点属性绑定**，
                        安全可用。

                      结构：64rpx 圆形头像（`--r-full`，与 `AppSkeleton` 既有规格同源）
                        有头像 → <image> 采用「等比填充 + 裁切」模式（**必须固定宽高**，否则 App 端按原图撑破布局）
                        无头像 → **纯 CSS 中性占位**（圆形底 + 头/肩色块；零图片资源、零 emoji）
                        右侧次要文字是本块**唯一的可点暗示** ⇒ 点击整块 → ActionSheet。
                    -->
                    <view class="mine__avatar" @tap="onAvatarTap">
                        <view class="mine__avatar-thumb">
                            <image
                                v-if="avatarSrc"
                                class="mine__avatar-img"
                                :src="avatarSrc"
                                mode="aspectFill"
                                @error="onAvatarImageError"
                            />
                            <view v-else class="mine__avatar-ph">
                                <view class="mine__avatar-ph-head"></view>
                                <view class="mine__avatar-ph-body"></view>
                            </view>
                        </view>
                        <text class="mine__avatar-tip">{{ avatarTip }}</text>
                    </view>

                    <view v-if="profileLoading">
                        <AppSkeleton variant="profile" />
                    </view>

                    <AppErrorState
                        v-else-if="profileError"
                        variant="inline"
                        :text="profileErrorText"
                        retry-text="重试"
                        @retry="onRetryProfile"
                    />

                    <template v-else>
                        <!--
                          ★ 个人资料区信息行（2026-09-18 视觉优化后的**统一结构**）
                          结构逐行一致：「左字段名 + 右侧值 +（可编辑行的）右箭头」，由 `profileRows`
                          数据驱动（`v-for`）；后续新增性别 / 出生日期等档案字段时**只追加数组项**即可。

                          ★ 为什么值不交给 C-20 的 `value` 位（2026-09-17 人工验收缺陷的根因，勿回退）：
                            C-20 的右侧 `tail` 区是 `flex-shrink: 0`（**不可收缩**），而「`value` 值 +
                            箭头 + `tail` 插槽」**全部渲染在该区内** ⇒ 值一旦变长，tail 便固定占满其
                            内容宽度，把左侧字段名压到 0 宽后**溢出绘制** ⇒ 与值视觉重叠
                            （不是字号/间距问题，是宽度分配问题）。
                          ⇒ 修法：**值改由本页承载**，放进 C-20 的默认插槽（位于 `.lrow__body`，
                            外层 `flex: 1 + min-width: 0`，**天然可收缩**）⇒ 长值单行省略不换行；
                            `tail` 只余 C-20 自带的箭头（宽度固定）。
                          范围：**仅本页模板与样式**；C-20 `AppListRow` 的契约与实现**零改动**。

                          ★ 操作入口与「值」的分离（本轮要求）：不再渲染「去设置」/「编辑昵称」文字动作；
                            入口 = **整行可点 + 右箭头**（`arrow=true` 既是视觉指示，也是 C-20 派发
                            `tap` 的前提条件）。功能不变：整行点击 → SC-17。
                        -->
                        <AppListRow
                            v-for="(row, i) in profileRows"
                            :key="row.key"
                            :arrow="row.editable"
                            :last="i === profileRows.length - 1"
                            @tap="onProfileRowTap(row)"
                        >
                            <view class="mine__row">
                                <text class="mine__row-label">{{ row.label }}</text>
                                <view class="mine__row-value">
                                    <text
                                        class="mine__row-text"
                                        :class="{ 'mine__row-text--unset': row.unset }"
                                    >{{ row.value }}</text>
                                </view>
                                <!-- 行级操作文案（当前仅「邮箱」行：绑定 / 更换）——链接色，位于箭头左侧 -->
                                <text v-if="row.action" class="mine__row-action">{{ row.action }}</text>
                            </view>

                            <!--
                              只读行（无箭头）放一个**与箭头等宽等距的不可见占位**，使两行「值」的
                              右边缘对齐（视觉统一）。该占位不承载文案、不可点、无语义。
                            -->
                            <template #tail>
                                <view v-if="!row.editable" class="mine__gutter"></view>
                            </template>
                        </AppListRow>
                    </template>
                </AppCard>

                <!-- ② 功能列表（8 项，顺序与 S1-C SC-18 ② 逐字一致） -->
                <AppCard class="mine__block">
                    <AppListRow
                        v-for="(item, i) in funcItems"
                        :key="item.key"
                        :title="item.label"
                        :arrow="item.enabled"
                        :disabled="!item.enabled"
                        :last="i === funcItems.length - 1"
                        @tap="onFunc(item)"
                    />
                </AppCard>

                <!-- ③ 危险操作区（与上方列表明显视觉分隔；两套确认强度不同） -->
                <AccountDangerZone
                    :disabled="dangerDisabled"
                    hint="退出登录只结束当前会话；注销账号为不可逆的终局操作。"
                    @logout="onLogoutTap"
                    @close="onCloseTap"
                />
            </view>
        </view>

        <!-- 退出登录：普通确认（中性色、单点确认） -->
        <AppModal
            :show="logoutShow"
            mode="confirm"
            title="退出登录"
            confirm-text="退出"
            cancel-text="取消"
            :confirm-disabled="logoutSubmitting"
            @cancel="onLogoutCancel"
            @confirm="onLogoutConfirm"
        >
            <text class="mine__mt">退出后需重新登录</text>
            <text class="mine__mt mine__mt--strong">你的数据会保留在账号中，重新登录即可恢复</text>
            <text class="mine__mt mine__mt--sub">同时会清除本机缓存，并取消已注册的系统提醒通知。</text>
        </AppModal>

        <!-- 注销账号：强确认（danger：红色 + 后果清单 + 文本输入 + 密码输入） -->
        <AppModal
            :show="closeShow"
            mode="danger"
            title="注销账号"
            confirm-text="确认注销"
            cancel-text="取消"
            :confirm-disabled="closeConfirmDisabled"
            @cancel="onCloseCancel"
            @confirm="onCloseConfirm"
        >
            <text class="mine__mt">注销后，以下内容将按隐私政策及法律法规删除或匿名化：</text>
            <text class="mine__mt mine__mt--item">· 账号本身</text>
            <text class="mine__mt mine__mt--item">· 全部健康数据</text>
            <text class="mine__mt mine__mt--item">· 健康目标与提醒</text>
            <text class="mine__mt mine__mt--item">· 导出产生的临时文件</text>
            <text class="mine__mt mine__mt--danger">此操作不可撤销，账号将无法恢复，且无等待期。</text>

            <view class="mine__field">
                <AppInput
                    v-model="closeText"
                    label="请输入「注销账号」以确认"
                    placeholder="注销账号"
                    :maxlength="10"
                    :disabled="closeSubmitting"
                />
            </view>

            <view class="mine__field">
                <AppInput
                    v-model="closePassword"
                    label="登录密码"
                    placeholder="请输入当前登录密码"
                    :password="true"
                    :maxlength="64"
                    :disabled="closeSubmitting"
                />
            </view>
        </AppModal>

        <!-- 邮箱绑定 / 换绑弹层（B4-2 第二批；默认插槽承载 EmailBindPanel；
             关闭 / 点遮罩收起 ⇒ 组件卸载 ⇒ clearSensitive() + disposeTimers()） -->
        <AppModal
            v-model:show="emailPanelShow"
            mode="confirm"
            title="邮箱绑定"
            confirm-text="关闭"
            :show-cancel="false"
            @confirm="onEmailPanelClose"
        >
            <EmailBindPanel
                :email-bound="emailBound"
                :email-masked="emailMasked"
                @success="onEmailBindSuccess"
            />
        </AppModal>

        <!-- ⑦ 底部 tabBar -->
        <AppTabBar :items="tabItems" current="mine" @select="onTabSelect" />

        <!-- 轻提示宿主（退出 / 注销 / 失败提示由本页经此渲染） -->
        <AppToast />

        <!-- 开发环境页面预览器（仅 H5 非生产环境渲染；生产构建下为空节点，不影响正式功能） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppNavBar from '../../components/AppNavBar.vue'
import AppCard from '../../components/AppCard.vue'
import AppListRow from '../../components/AppListRow.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppModal from '../../components/AppModal.vue'
import AppInput from '../../components/AppInput.vue'
import AppTabBar from '../../components/AppTabBar.vue'
import AppToast from '../../components/AppToast.vue'
import AccountDangerZone from '../../components/AccountDangerZone.vue'
import EmailBindPanel from '../../components/EmailBindPanel.vue'
// 开发环境专用页面预览器（**仅 H5 + 非生产**生效；不注册进 `pages.json`、不计入 25 页）
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { ROUTES, navigateTo, reLaunch, requireLogin } from '../../utils/route'
import { useUserStore } from '../../store/user'
import { logout as logoutApi, closeAccount } from '../../api/auth'
import { getProfile } from '../../api/profile'
import {
    AVATAR_PICK_COUNT,
    AVATAR_PICK_SIZE_TYPE,
    AVATAR_SOURCE_ALBUM,
    AVATAR_SOURCE_CAMERA,
    uploadAvatar,
    downloadAvatar,
    deleteAvatar,
    clearAvatarCache,
    AVATAR_UPLOAD_FIELD,
    isSessionExpired
} from '../../utils/avatar'
import { showToast } from '../../utils/toast'
import { errorText, fieldErrorText } from '../../utils/request'
import { NETWORK_BANNER_MS } from '../../utils/config'

/** 昵称为空时的展示文案（S1-C SC-18 ⑩ 原文，**不得**写成"未建档"） */
const NICKNAME_UNSET = '未设置昵称'

/** 注销强确认必须逐字输入的文本（与 `backend/app/api/v1/account.py` 的 `confirm_text` 一致） */
const CLOSE_CONFIRM_WORD = '注销账号'

/** 离线时写操作的统一提示（S1-C SC-18 ⑭ 逐字） */
const OFFLINE_OP_TEXT = '当前网络不可用，请联网后操作'

/** 默认头像提示（**本页头像区唯一的可点暗示**；不承诺、无医学语义、无 emoji） */
const AVATAR_TIP_UNSET = '点击设置头像'
const AVATAR_TIP_SET = '点击更换头像'

/** 动作表条目（顺序即 `tapIndex` 契约；「恢复默认头像」仅在有头像时追加） */
const AVATAR_ACTION_ALBUM = '从相册选择'
const AVATAR_ACTION_CAMERA = '拍照'
const AVATAR_ACTION_RESTORE = '恢复默认头像'

/** 选图失败的中性提示（权限被拒 / 无法唤起；**不回显任何内部信息**） */
const AVATAR_ALBUM_DENIED = '无法打开相册，请在系统设置中允许访问相册后重试'
const AVATAR_CAMERA_DENIED = '无法打开相机，请在系统设置中允许使用相机后重试'

/** 取字符串（空值 / 非字符串 → ''） */
function textOf(value) {
    if (value === null || value === undefined) {
        return ''
    }
    return String(value)
}

/**
 * 头像操作的错误文案：**只用统一请求层的安全文案**。
 * 422 的字段级明细优先（如「图片大小超出上限（最大 2 MiB）」），否则回落到顶层 `message`。
 * **绝不**拼接 `err` 本体 / 堆栈 / `httpStatus` / URL —— 用户可见文本不得含内部信息。
 */
function avatarErrorText(err) {
    const fieldMsg = fieldErrorText(err, AVATAR_UPLOAD_FIELD)
    if (fieldMsg) {
        return fieldMsg
    }
    return errorText(err)
}

export default {
    components: {
        AppNavBar: AppNavBar,
        AppCard: AppCard,
        AppListRow: AppListRow,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState,
        AppOfflineBar: AppOfflineBar,
        AppModal: AppModal,
        AppInput: AppInput,
        AppTabBar: AppTabBar,
        AppToast: AppToast,
        AccountDangerZone: AccountDangerZone,
        EmailBindPanel: EmailBindPanel,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /* ── 网络状态 ── */
            /** 离线（页面仍可查看本地已有信息） */
            offline: false,
            /** 网络恢复横幅是否可见（3s） */
            restoredVisible: false,
            /** 网络监听回调句柄 / 定时器句柄 */
            networkHandler: null,
            bannerTimer: null,
            /** 本次 onShow 之前是否已加载过（用于「返回本页刷新资料」） */
            entered: false,

            /* ── ① 个人资料区 ── */
            /** 用户名（优先取本地缓存，离线可用） */
            username: '',
            /** 昵称（来自 P-01；空串 = 未设置） */
            nickname: '',
            /** 资料区加载中（仅资料区骨架，列表立即可用） */
            profileLoading: true,
            /** 资料区失败（用户信息或档案获取失败） */
            profileError: false,
            profileErrorText: '资料加载失败，点击重试',

            /* ── ① 个人资料区：邮箱绑定态（**唯一数据源 = A-06** 的 `email_bound` / `email_masked`） ── */
            /** 当前账号是否已绑定**已验证**邮箱（A-06 `email_bound`；**不本地推断、不新增接口**） */
            emailBound: false,
            /** 后端生成的掩码邮箱（A-06 `email_masked`；未绑定时为空串，**前端不自行生成**） */
            emailMasked: '',
            /** 邮箱绑定 / 换绑弹层可见性（关闭即卸载面板 ⇒ 触发 clearSensitive() / disposeTimers()） */
            emailPanelShow: false,

            /* ── ① 个人资料区：S4-2C 头像 ── */
            /** 头像内存路径（`uni.downloadFile` 的 tempFilePath；空 = 渲染 CSS 默认头像） */
            avatarSrc: '',
            /** 服务端头像版本戳（P-01 `profile.avatar_updated_at`；null = 未设置头像） */
            avatarUpdatedAt: null,
            /** 头像下载中（防并发重复下载） */
            avatarLoading: false,
            /** 头像上传 / 恢复默认 提交中（防重） */
            avatarSubmitting: false,

            /* ── ③ 危险操作区：两套弹层 ── */
            /** ① 退出登录（普通确认） */
            logoutShow: false,
            logoutSubmitting: false,
            /** ② 注销账号（强确认） */
            closeShow: false,
            closeSubmitting: false,
            /** 强确认文本输入（必须逐字等于「注销账号」） */
            closeText: '',
            /** 强确认密码输入（**仅内存，绝不落盘**） */
            closePassword: '',

            tabItems: [
                { key: 'home', label: '首页', enabled: true },
                { key: 'record', label: '记录中心', enabled: true },
                { key: 'trend', label: '趋势', enabled: true },
                { key: 'mine', label: '我的', enabled: true }
            ]
        }
    },
    computed: {
        /** 用户名展示（空 → 中性占位，不编造） */
        usernameText: function () {
            return this.username ? this.username : '—'
        },
        /** 头像提示文案（有版本戳 = 已设置头像） */
        avatarTip: function () {
            return this.avatarUpdatedAt ? AVATAR_TIP_SET : AVATAR_TIP_UNSET
        },
        /**
         * 动作表条目（顺序 = `onAvatarAction` 的 index 契约）。
         * ★ **无头像时不出现「恢复默认头像」**：避免"点了没反应"的假入口
         *   （与 C-20 `tapEnabled = !disabled && arrow` 的既有口径同源；S4-2A §十一）。
         */
        avatarSheetItems: function () {
            const items = [AVATAR_ACTION_ALBUM, AVATAR_ACTION_CAMERA]
            if (this.avatarUpdatedAt) {
                items.push(AVATAR_ACTION_RESTORE)
            }
            return items
        },

        /** 昵称展示（S1-C ⑩：空 → 「未设置昵称」） */
        nicknameText: function () {
            return this.nickname ? this.nickname : NICKNAME_UNSET
        },
        /**
         * 邮箱展示值（**唯一数据源 = A-06**）：
         *   已绑定 ⇒ 后端掩码 `email_masked`（空则中性「已绑定」占位，**绝不**回退完整邮箱）；
         *   未绑定 ⇒ 「未绑定」（次要色）。
         */
        emailValueText: function () {
            if (!this.emailBound) {
                return '未绑定'
            }
            return textOf(this.emailMasked) || '已绑定'
        },
        /** 邮箱行操作文案（未绑定 ⇒ 绑定；已绑定 ⇒ 更换） */
        emailActionText: function () {
            return this.emailBound ? '更换' : '绑定'
        },
        /**
         * ① 个人资料区信息行 —— **统一结构**的数据源（左字段名 + 右值 + 可编辑行的箭头）。
         *
         * ★ 为什么做成「行数组」而不是写死两行：
         *   本区后续还要承载性别 / 出生日期等档案字段（同属 `P-01` 返回的 `profile`）。
         *   新增字段时**只需在本数组追加一项**，模板与样式**零改动**；且天然保证所有行共用同一套
         *   布局（不会再出现某一行单独排布、风格不一）。`key` 同时用于 `:key` 与点击分派。
         *
         * 字段含义：
         *   key      —— 行标识（用于 `:key` 与 `onProfileRowTap` 分派，不对外暴露）；
         *   label    —— 左侧字段名；
         *   value    —— 右侧展示值（**已格式化**；空态文案亦由本数组给出）；
         *   unset    —— 该值是否处于「未设置」空态（空态走次要文字色，与真实值区分）；
         *   editable —— 是否可点进下级。true ⇒ C-20 渲染右箭头且整行可点；false ⇒ 纯只读行。
         *
         * ★ 只读行为何不带箭头：C-20 的 `tapEnabled = !disabled && arrow` ⇒ 无下级的行必须
         *   `arrow=false`，否则会变成「点了才知道没反应」的假入口（C-20 组件注释即为此口径）。
         *   为让只读行与可编辑行的「值」右边缘对齐，只读行在 `tail` 槽内放等宽占位（`.mine__gutter`）。
         */
        profileRows: function () {
            return [
                {
                    key: 'username',
                    label: '用户名',
                    value: this.usernameText,
                    unset: !this.username,
                    editable: false
                },
                {
                    key: 'nickname',
                    label: '昵称',
                    value: this.nicknameText,
                    unset: !this.nickname,
                    editable: true
                },
                {
                    key: 'email',
                    label: '邮箱',
                    value: this.emailValueText,
                    unset: !this.emailBound,
                    editable: true,
                    action: this.emailActionText
                }
            ]
        },
        /**
         * ② 功能列表（8 项，顺序与 S1-C SC-18 ② 逐字一致）。
         8 项**全部可点**（S4-1 后已无置灰项）：后 3 项 -> SC-23 / SC-24 / SC-25，
         * 三页已于 S4-1 随 `pages.json` 注册（22 -> 25 页）并接线，**不存在死链接**。
         */
        funcItems: function () {
            return [
                { key: 'password', label: '修改密码', enabled: true },
                { key: 'profile', label: '健康档案', enabled: true },
                { key: 'goal', label: '健康目标', enabled: true },
                { key: 'reminder', label: '健康提醒', enabled: true },
                { key: 'data', label: '数据管理', enabled: true },
                { key: 'privacy', label: '隐私政策', enabled: true },
                { key: 'terms', label: '用户协议', enabled: true },
                { key: 'about', label: '关于', enabled: true }
            ]
        },
        /** 危险区置灰（离线或正在提交）—— 注意：**置灰不阻断点击**，由本页给明确提示 */
        dangerDisabled: function () {
            return this.offline || this.logoutSubmitting || this.closeSubmitting
        },
        /** 强确认按钮可用性：文本逐字命中 + 密码非空 + 未在提交中 */
        closeConfirmDisabled: function () {
            if (this.closeSubmitting) {
                return true
            }
            if (textOf(this.closeText).trim() !== CLOSE_CONFIRM_WORD) {
                return true
            }
            return !textOf(this.closePassword)
        }
    },
    onLoad: function () {
        // 未登录守卫（S1-C ⑬：访客 → SC-03）；守卫内部已清栈跳转
        if (!requireLogin()) {
            return
        }

        // 用户名先取本地缓存值 ⇒ 离线时资料区仍可查看（S1-C ⑭）
        const store = useUserStore()
        store.hydrate()
        this.username = store.username

        // 网络恢复 → 重新加载资料区（S1-C ⑭；只刷当前页、不自动重放写操作）
        const self = this
        this.networkHandler = function (res) {
            self.handleNetworkChange(res)
        }
        uni.onNetworkStatusChange(this.networkHandler)

        this.refreshProfile()
    },
    onShow: function () {
        // 返回本页刷新资料区（SC-17 保存后昵称需同步）；首次进入由 onLoad 负责
        if (this.entered) {
            this.refreshProfile(true)
        }
        this.entered = true
    },
    onUnload: function () {
        this.clearBannerTimer()
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
        // 释放敏感字段的内存引用（**不落盘、不落草稿**）
        this.closePassword = ''
        this.closeText = ''
    },
    onHide: function () {
        // 空实现：本页无后台任务、无计时型业务
    },
    methods: {
        /* ───────────── ① 个人资料区 ───────────── */

        /**
         * 并行拉取 `A-06`（用户名 / 建档标记）与 `P-01`（昵称）。
         * 两个请求**各自独立结算**：任一失败只影响资料区，功能列表与危险区不受影响（S1-C ⑫）。
         * @param {boolean} silent 静默刷新（已渲染过时不显示骨架）
         */
        refreshProfile: function (silent) {
            const self = this
            if (!silent) {
                this.profileLoading = true
            }
            this.profileError = false

            const mePromise = useUserStore().refreshMe().then(function (res) {
                return { ok: true, res: res, err: null }
            }, function (err) {
                return { ok: false, res: null, err: err }
            })

            const profilePromise = getProfile().then(function (res) {
                return { ok: true, res: res, err: null }
            }, function (err) {
                return { ok: false, res: null, err: err }
            })

            return Promise.all([mePromise, profilePromise]).then(function (arr) {
                const me = arr[0]
                const pf = arr[1]
                self.profileLoading = false

                if (me.ok) {
                    self.username = useUserStore().username
                    // ★ 邮箱绑定态：**只消费 A-06** 的 `email_bound` / `email_masked`
                    //   （不新增接口、不改 store、不本地推断；缺失时回落「未绑定」）
                    const meData = me.res && me.res.data ? me.res.data : {}
                    self.emailBound = meData.email_bound === true
                    self.emailMasked = textOf(meData.email_masked)
                } else if (me.err && me.err.isNetwork) {
                    self.offline = true
                }

                if (pf.ok) {
                    const data = pf.res && pf.res.data ? pf.res.data : {}
                    const profile = data.profile ? data.profile : {}
                    self.nickname = textOf(profile.nickname)
                    // S4-2C：头像版本戳（P-01 已追加 `avatar_updated_at`）⇒ 驱动头像复用/下载
                    // 注意：`null` 必须与「空串」区分开 —— null 才代表「未设置头像」
                    self.avatarUpdatedAt = profile.avatar_updated_at === undefined
                        ? null
                        : profile.avatar_updated_at
                    self.syncAvatar()
                } else if (pf.err && pf.err.isNetwork) {
                    self.offline = true
                }

                // 只有「非网络类失败」才落到资料区失败态；离线由离线条 + 本地缓存承载（S1-C ⑭）
                const meFailed = !me.ok && !(me.err && me.err.isNetwork)
                const pfFailed = !pf.ok && !(pf.err && pf.err.isNetwork)
                self.profileError = meFailed || pfFailed
            })
        },
        onRetryProfile: function () {
            this.refreshProfile()
        },
        /**
         * 资料行点击分派（只有可编辑行会走到这里：只读行 `arrow=false` ⇒ C-20 不派发 `tap`）。
         * 下级：昵称 → SC-17；邮箱 → 页内邮箱绑定弹层（B4-2 第二批）。
         * 后续新增性别 / 出生日期等可编辑行时，在此追加分支即可。
         */
        onProfileRowTap: function (row) {
            if (!row || !row.editable) {
                return
            }
            if (row.key === 'nickname') {
                this.onEditNickname()
            }
            if (row.key === 'email') {
                this.onEmailTap()
            }
        },
        /** 昵称行（整行可点）→ SC-17（离线禁止编辑由 SC-17 自行承载并提示） */
        onEditNickname: function () {
            navigateTo(ROUTES.PROFILE_EDIT)
        },

        /* ───────────── ① 个人资料区：邮箱绑定 / 换绑（A2；B4-2 第二批） ───────────── */

        /**
         * 邮箱行（整行可点）→ 打开 `AppModal` 承载 `EmailBindPanel`。
         * 绑定态由 A-06 提供（`emailBound` / `emailMasked`）⇒ 面板只消费、不推断、不读完整邮箱。
         */
        onEmailTap: function () {
            this.emailPanelShow = true
        },
        /** 关闭邮箱弹层（`v-if` 收起 ⇒ `EmailBindPanel` 卸载 ⇒ clearSensitive() + disposeTimers()） */
        onEmailPanelClose: function () {
            this.emailPanelShow = false
        },
        /**
         * `EmailBindPanel` 成功出口：**关闭弹层 → 重新请求 A-06 → 用新的 `email_bound`/`email_masked` 刷新展示**。
         * ★ 父页面**不**依据用户刚输入的邮箱假设绑定成功、**不**自行生成 `email_masked`、
         *   **不**直接改 store 假装后端已更新 —— A-06 是成功后的**最终显示权威**。
         */
        onEmailBindSuccess: function () {
            this.emailPanelShow = false
            this.refreshProfile(true)
        },

        /* ───────────── ① 个人资料区：S4-2C 头像（S4-2A §十 / §十一） ───────────── */

        /**
         * 点击头像区 → 动作选择弹层（**只列当前真正可用的动作**）。
         *
         * ★ 采用 `uni.showActionSheet`：S4-2C 需求方指令把本处交互明确为
         *   「ActionSheet：从相册选择 / 拍照 /（有头像时）恢复默认头像 / 取消」，且
         *   **来源选择已由 ActionSheet 承担** ⇒ `chooseImage` 只传单一 `sourceType`。
         *   沿用平台原生动作表**不新增组件、不改 C-06 `AppModal` 契约**。
         */
        onAvatarTap: function () {
            if (this.avatarSubmitting) {
                return
            }
            if (this.offline) {
                showToast('info', OFFLINE_OP_TEXT)
                return
            }
            const self = this
            uni.showActionSheet({
                itemList: this.avatarSheetItems,
                success: function (res) {
                    self.onAvatarAction(res ? res.tapIndex : -1)
                },
                fail: function () {
                    // 用户取消动作表：**静默**（不弹错误提示）
                }
            })
        },
        /** 动作表分派（index 契约与 `avatarSheetItems` 顺序严格一致） */
        onAvatarAction: function (index) {
            if (index === 0) {
                this.chooseAndUploadAvatar(AVATAR_SOURCE_ALBUM)
                return
            }
            if (index === 1) {
                this.chooseAndUploadAvatar(AVATAR_SOURCE_CAMERA)
                return
            }
            if (index === 2 && this.avatarUpdatedAt) {
                this.onAvatarRestoreDefault()
            }
        },
        /**
         * 选图 → 上传。固定 `count: 1` / `sizeType: ['compressed']`；
         * `sourceType` **只传用户刚选定的单一来源**（`album` 或 `camera`）——
         * 不在 ActionSheet 之后再弹一次「相册 / 相机」二次选择。
         * **不使用 `uni.chooseMedia`、不引入裁剪库**（S4-2C §三）。
         */
        chooseAndUploadAvatar: function (source) {
            const self = this
            uni.chooseImage({
                count: AVATAR_PICK_COUNT,
                sizeType: AVATAR_PICK_SIZE_TYPE,
                sourceType: [source],
                success: function (res) {
                    const paths = (res && res.tempFilePaths) || []
                    if (paths.length > 0 && paths[0]) {
                        self.submitAvatar(paths[0])
                    }
                },
                fail: function (err) {
                    self.onAvatarPickFail(err, source)
                }
            })
        },
        /**
         * 选图失败：**用户取消不提示**；其余（含相册 / 相机权限被拒）给**中性、明确**提示
         * —— 只说"去系统设置开启权限"，不回显路径 / 错误码 / HTTP 内部信息。
         */
        onAvatarPickFail: function (err, source) {
            const msg = err && err.errMsg ? String(err.errMsg) : ''
            if (msg.indexOf('cancel') >= 0) {
                return
            }
            showToast('info', source === AVATAR_SOURCE_CAMERA
                ? AVATAR_CAMERA_DENIED
                : AVATAR_ALBUM_DENIED)
        },
        /** 上传头像（写操作：**不自动重试**；401 由头像传输层同源刷新后重放一次） */
        submitAvatar: function (filePath) {
            const self = this
            this.avatarSubmitting = true
            uploadAvatar(filePath).then(function (body) {
                self.avatarSubmitting = false
                const data = body && body.data ? body.data : {}
                self.avatarUpdatedAt = data.avatar_updated_at === undefined
                    ? null
                    : data.avatar_updated_at
                showToast('success', (body && body.message) || '头像已更新')
                // 传输层已失效旧缓存 ⇒ 此处**必然**重新下载新头像（不会复用旧图）
                return self.syncAvatar()
            }, function (err) {
                self.avatarSubmitting = false
                if (isSessionExpired(err)) {
                    // 会话已失效：统一层已清态 + 已提示 + 已清栈回 SC-03 ⇒ **不重复提示**
                    return
                }
                showToast('error', avatarErrorText(err))
            })
        },
        /** 恢复默认头像（AV-02；UI 侧**只对有头像**派发到本方法，无头像不展示该入口） */
        onAvatarRestoreDefault: function () {
            const self = this
            if (this.avatarSubmitting) {
                return
            }
            this.avatarSubmitting = true
            deleteAvatar().then(function (body) {
                self.avatarSubmitting = false
                self.avatarUpdatedAt = null
                self.avatarSrc = ''
                showToast('success', (body && body.message) || '已恢复默认头像')
            }, function (err) {
                self.avatarSubmitting = false
                if (isSessionExpired(err)) {
                    return
                }
                showToast('error', avatarErrorText(err))
            })
        },
        /**
         * 按 P-01 的 `avatar_updated_at` 同步头像（**不新增头像 meta 接口**）：
         *   `null` ⇒ 清缓存 + CSS 默认头像（**不请求 AV-03**）；
         *   有值 ⇒ 命中内存缓存则零请求复用，否则下载。
         * **任何失败都降级默认头像**（绝不显示破图）；下载失败**不弹提示** ——
         * 离线时本页本就可查看（S1-C ⑭），弹提示只会制造噪声；401 的提示与跳转由统一层负责。
         */
        syncAvatar: function () {
            const self = this
            if (!this.avatarUpdatedAt) {
                clearAvatarCache()
                this.avatarSrc = ''
                return Promise.resolve()
            }
            if (this.avatarLoading) {
                return Promise.resolve()
            }
            this.avatarLoading = true
            return downloadAvatar(this.avatarUpdatedAt).then(function (tempPath) {
                self.avatarLoading = false
                self.avatarSrc = tempPath ? tempPath : ''
            }, function () {
                self.avatarLoading = false
                self.avatarSrc = ''
            })
        },
        /** `<image>` 渲染失败（文件损坏 / 取不到）⇒ 清缓存并降级默认头像（不显示破图） */
        onAvatarImageError: function () {
            clearAvatarCache()
            this.avatarSrc = ''
        },

        /* ───────────── ② 功能列表 ───────────── */

        /**
         * 功能入口跳转（C-20 仅在 `arrow=true` 时派发 `tap` ⇒ 置灰项不会进到这里）。
         * S4-1 起 8 项**全部已落地** => 本函数为每一项都建立分支（不再有"故意不建分支"的项）。
         */
        onFunc: function (item) {
            if (!item || !item.enabled) {
                return
            }
            if (item.key === 'password') {
                navigateTo(ROUTES.PASSWORD)
                return
            }
            if (item.key === 'profile') {
                navigateTo(ROUTES.PROFILE)
                return
            }
            if (item.key === 'goal') {
                navigateTo(ROUTES.GOAL)
                return
            }
            if (item.key === 'reminder') {
                navigateTo(ROUTES.REMINDER)
                return
            }
            if (item.key === 'data') {
                navigateTo(ROUTES.DATA)
                return
            }
            if (item.key === 'privacy') {
                navigateTo(ROUTES.PRIVACY)
                return
            }
            if (item.key === 'terms') {
                navigateTo(ROUTES.TERMS)
                return
            }
            if (item.key === 'about') {
                navigateTo(ROUTES.ABOUT)
            }
        },

        /* ───────────── ③ 危险操作区：① 退出登录（普通确认） ───────────── */

        onLogoutTap: function () {
            if (this.offline) {
                showToast('info', OFFLINE_OP_TEXT)
                return
            }
            this.logoutShow = true
        },
        onLogoutCancel: function () {
            if (this.logoutSubmitting) {
                return
            }
            this.logoutShow = false
        },
        onLogoutConfirm: function () {
            if (this.logoutSubmitting) {
                return
            }
            const self = this
            this.logoutSubmitting = true
            logoutApi().then(function () {
                self.logoutSubmitting = false
                self.logoutShow = false
                // S4-2C：**先**丢弃头像内存缓存（避免下一账号复用上一账号的 tempFilePath）
                clearAvatarCache()
                self.avatarSrc = ''
                self.avatarUpdatedAt = null
                // 清态统一走 store（内部先取消已注册系统通知再删 9 项 —— I-01）
                useUserStore().clearSessionAndCache()
                showToast('success', '已退出登录')
                reLaunch(ROUTES.LOGIN)
            }, function (err) {
                // 失败：明确提示 + **不跳转、不清态**（服务端会话未失效即视为未退出）
                self.logoutSubmitting = false
                self.logoutShow = false
                showToast('error', errorText(err))
            })
        },

        /* ───────────── ③ 危险操作区：② 注销账号（强确认） ───────────── */

        onCloseTap: function () {
            if (this.offline) {
                showToast('info', OFFLINE_OP_TEXT)
                return
            }
            this.resetCloseForm()
            this.closeShow = true
        },
        onCloseCancel: function () {
            if (this.closeSubmitting) {
                return
            }
            this.closeShow = false
            this.resetCloseForm()
        },
        onCloseConfirm: function () {
            if (this.closeConfirmDisabled) {
                return
            }
            const self = this
            this.closeSubmitting = true
            closeAccount({
                password: this.closePassword,
                confirm_text: textOf(this.closeText).trim()
            }).then(function () {
                self.closeSubmitting = false
                self.closeShow = false
                // S4-2C：**先**丢弃头像内存缓存（避免下一账号复用上一账号的 tempFilePath）
                clearAvatarCache()
                self.avatarSrc = ''
                self.avatarUpdatedAt = null
                self.resetCloseForm()
                useUserStore().clearSessionAndCache()
                showToast('success', '账号已注销')
                reLaunch(ROUTES.LOGIN)
            }, function (err) {
                // 失败：明确提示 + **不跳转**（不得出现"已注销但实际失败"的假成功）；
                // 保留已填内容便于修正后重试（密码仅存内存，离开页面即释放）
                self.closeSubmitting = false
                showToast('error', errorText(err))
            })
        },
        /** 清空强确认输入（**密码不进任何存储**） */
        resetCloseForm: function () {
            this.closeText = ''
            this.closePassword = ''
        },

        /* ───────────── 网络状态 ───────────── */

        handleNetworkChange: function (res) {
            const online = !!(res && res.isConnected)
            if (!online) {
                this.offline = true
                return
            }
            // 恢复：撤下离线标记 → 展示 3s 恢复横幅 → 重新加载资料区
            this.offline = false
            this.showRestoredBanner()
            this.refreshProfile(true)
        },
        showRestoredBanner: function () {
            const self = this
            this.restoredVisible = true
            this.clearBannerTimer()
            this.bannerTimer = setTimeout(function () {
                self.restoredVisible = false
                self.bannerTimer = null
            }, NETWORK_BANNER_MS)
        },
        clearBannerTimer: function () {
            if (this.bannerTimer) {
                clearTimeout(this.bannerTimer)
                this.bannerTimer = null
            }
        },

        /* ───────────── tabBar ───────────── */

        /**
         * tabBar 切换：「我的」即当前页，C-11 **不对当前项派发事件**（故无 mine 分支）；
         * 其余三项均为已实现页面（SC-06 / SC-07 / SC-11）⇒ 清栈切换。
         */
        onTabSelect: function (item) {
            if (!item || !item.key) {
                return
            }
            if (item.key === 'home') {
                reLaunch(ROUTES.HOME)
                return
            }
            if (item.key === 'record') {
                reLaunch(ROUTES.RECORD)
                return
            }
            if (item.key === 'trend') {
                reLaunch(ROUTES.TREND)
            }
        }
    }
}
</script>

<style scoped lang="scss">
.mine {
    min-height: 100vh;
    background-color: var(--s-page);
}

.mine__body {
    padding-top: var(--nav-total-h);
    /* 底部固定区 = tabBar 总高 + 区块间距 */
    padding-bottom: calc(var(--tabbar-total-h) + var(--section-gap));
}

/* 内容最大宽居中（DESIGN.md §10.4③） */
.mine__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.mine__notice {
    margin-bottom: var(--sp-5);
}

/* 区块节奏：卡片之间统一走 --section-gap */
.mine__block {
    margin-bottom: var(--section-gap);
}

/* ── ① 个人资料区：移动端信息行（左字段名 + 右值；值可收缩并单行省略） ──
   为什么不用 C-20 的 `value` 位：该值渲染在 `tail` 区内，而 `tail` 是 `flex-shrink: 0`
   ⇒ 长值会把左侧字段名挤压重叠（2026-09-17 实测：320px 屏下字段名被压到 0 宽后**溢出绘制**，
   与值重叠 8px）。此处三个关键约束**缺一不可**：
     ① 值容器 `flex: 1 + min-width: 0`（无 `min-width: 0` 则收缩不到内容宽度以下，省略号不生效）；
     ② 字段名 `flex-shrink: 0`（窄屏下优先保证字段名完整可读，绝不参与压缩）；
     ③ 文本 `display: block + nowrap + ellipsis`（`display: block` 用于覆盖 `text` 的 inline）。
   行结构（字段名 / 值 / 箭头）由 `profileRows` 统一给出 ⇒ 新增资料字段不会打破该布局。 */
.mine__row {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-width: 0;
}

/* 字段名（「用户名」/「昵称」）：与各列表行标题同字号同色，视觉口径一致 */
.mine__row-label {
    flex-shrink: 0;
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-regular;
    color: var(--t-2);
    letter-spacing: 0;
}

/* 值容器：占满剩余宽度；超长（如 20 字昵称）时单行省略，不挤压字段名、不换行撑高。
   `margin-left` 取 `--sp-5`（= 24rpx）而非更小的 `--sp-3`：值在超长时会**填满**整个剩余宽度，
   间距过小时字段名与值会在视觉上连成一句（读起来像同一个标签）
   ⇒ 用一档更宽的令牌，保证「字段名 / 值」在任何长度下都是两个可辨识的单元。 */
.mine__row-value {
    flex: 1;
    min-width: 0;
    margin-left: var(--sp-5);
    overflow: hidden;
}

/* 值文本 */
.mine__row-text {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
    text-align: right;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* 「未设置」空态值：走次要文字色 + 常规字重，与已填写的真实值（--t-1 加粗）一眼可分 */
.mine__row-text--unset {
    font-weight: $fw-regular;
    color: var(--t-3);
}

/* 行级操作文案（当前仅「邮箱」行：绑定 / 更换）——
   链接色 + 常规字重，位于 C-20 箭头**左侧**（箭头仍作「可点进下级」的标准指示）；
   与左侧「值」用 --sp-5 拉开，避免「未绑定 绑定」在视觉上连成一句。 */
.mine__row-action {
    flex-shrink: 0;
    margin-left: var(--sp-5);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    font-weight: $fw-regular;
    color: var(--t-link);
    letter-spacing: 0;
}

/* 只读行（无箭头）的值右对齐占位：**与 C-20 `.lrow__chevron` 的占位完全等宽等距**
   （`width: 8px` + `margin-left: var(--sp-2)`），使只读行与可编辑行的「值」右边缘对齐。
   不可点、无文案、无语义；本页经 `tail` 槽注入，**不改动 C-20 组件本身**。
   说明：`8px` 与 C-20 箭头边长同值，属 `DESIGN.md §10.4②`「图标几何按 px 栅格对齐」口径。 */
.mine__gutter {
    width: 8px;
    margin-left: var(--sp-2);
}

/* ── 弹层正文（两套确认共用文字节奏，颜色/强度由各自语义决定） ── */
.mine__mt {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-2);
    letter-spacing: 0;
}

.mine__mt + .mine__mt {
    margin-top: var(--sp-3);
}

/* 退出登录：核心承诺句加重（数据保留） */
.mine__mt--strong {
    font-weight: $fw-medium;
    color: var(--t-1);
}

/* 附注（次要信息：清缓存 + 取消系统通知） */
.mine__mt--sub {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
}

/* 注销后果清单逐条 */
.mine__mt--item {
    padding-left: var(--sp-4);
}

/* 注销终局提示：危险色（与退出的中性色形成明显区分） */
.mine__mt--danger {
    font-weight: $fw-medium;
    color: var(--t-danger);
}

/* ── S4-2C 头像区（资料行之上；S4-2E-UI 视觉优化；**全部走设计令牌**） ──
   S4-2E-UI 裁定：容器 128rpx 居中视觉主体、row → column、
   上沿 var(--sp-2)、提示文字 var(--sp-4)、描边 var(--b-border)。
   尺寸字面量不属 DESIGN.md §14.7 裸值判据的属性集（该集合不含尺寸属性），
   取值按 §10.4 的 rpx 栅格；颜色 / 圆角 / 间距 / 字号一律走令牌。
   注：S4-2A §五 第 3 条（尺寸与 AppSkeleton 同规格）已由本批解除，仅登记不回写历史正本。 */
.mine__avatar {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: var(--sp-2);
    padding-bottom: var(--sp-5);
    border-bottom: 1rpx solid var(--b-line);
    margin-bottom: var(--sp-5);
}

/* 圆形头像容器：固定边长 + `overflow: hidden` 保证 `aspectFill` 不外溢 */
.mine__avatar-thumb {
    width: 128rpx;
    height: 128rpx;
    flex-shrink: 0;
    border-radius: var(--r-full);
    overflow: hidden;
    background-color: var(--s-sunken);
    border: 1rpx solid var(--b-border);
}

/* 真实头像：铺满容器、等比裁切（App 端必须有确定宽高） */
.mine__avatar-img {
    width: 128rpx;
    height: 128rpx;
    display: block;
}

/* 默认头像占位（纯 CSS 中性剪影：肩部圆条 + 头部圆点；无图片、无 emoji） */
.mine__avatar-ph {
    width: 128rpx;
    height: 128rpx;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-end;
    overflow: hidden;
}

.mine__avatar-ph-head {
    width: 54rpx;
    height: 54rpx;
    border-radius: var(--r-full);
    background-color: var(--t-4);
    margin-bottom: var(--sp-2);
}

.mine__avatar-ph-body {
    width: 96rpx;
    height: 52rpx;
    border-radius: var(--r-full) var(--r-full) var(--r-xs) var(--r-xs);
    background-color: var(--t-4);
}

/* 可点提示（次要文字色；本块唯一的可点暗示） */
.mine__avatar-tip {
    margin-top: var(--sp-4);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* 强确认的两个输入位（与上方清单拉开节奏） */
.mine__field {
    margin-top: var(--sp-5);
}
</style>
