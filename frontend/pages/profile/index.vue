<template>
    <!--
      SC-16 健康档案页（pages/profile/index）
      依据：S1-C §二 SC-16（① 顶部栏「健康档案」+【编辑】→ SC-17 / ② 基础信息块 /
            ③ 身体基础值块 / ④ 健康背景块 / ⑤ 未填写字段 / ⑥ 页脚注 D-1）｜
            DESIGN.md §10.3（**A 类系统导航栏**）/ §11 / §12 / §13 / §14.8（目标体重禁用第二数据源）

      顶栏：**A 类系统导航栏**（`DESIGN.md §10.3` 的 B 类自绘顶栏清单**不含** SC-16）——
            标题由 `pages.json` 指定，本页**不得**加 `navigationStyle: custom`。
            原型 ① 的【编辑】在系统导航栏放不下 ⇒ **照 SC-12 / SC-14 先例落内容区顶部**。

      数据来源：
        · P-01 `GET /profile`          → 档案 9 字段（**主请求**，决定 加载 / 失败 / 离线）
        · G-01 `GET /goals`（**只读**） → **目标体重**（原型 ③ 要求展示；D-1：唯一数据源 = `health_goal`）
          ⇒ G-01 为**辅助请求**，失败**不拖垮整页**，目标体重显示「—」
            （与 C-21「最近值区加载失败静默显示 `—`」同先例）。

      ★ D-1 / `DESIGN.md §14.8`：目标体重**只读展示 + 跳转 SC-12**；**本页不得出现任何编辑控件**。

      ★ 医疗红线（S1-C SC-16 医疗红线）：健康背景三区块**只回显用户原文** ——
        **不做任何解读、不提取关键词、不打标签、不做风险提示、不出现"建议就医"**。

      状态覆盖（DESIGN.md §13 底线清单，逐项说明）：
        正常 → 分块回显；空字段显示「**未填写**」（**不得**写「未建档」）；
        空 → **逐块独立显示「未填写」，不出现整页空状态**（S1-C SC-16 ⑩：档案页恒有内容框架）；
             `profile_initialized === false` 时额外提示「档案尚未完善」+「去完善」→ SC-05；
        加载 → **分区骨架屏**（AppSkeleton variant="profile"）；
        失败 → `AppErrorState variant="full"` + 重试；
        未登录 → 路由守卫 → SC-03；
        离线 → ① 基础信息 + 身体基础值**命中缓存可看** + 「离线数据 · 更新于 <时间>」；
               ② **健康背景三字段默认不缓存** → 「**离线状态暂不可查看，请联网后查看**」（SC-16 ⑭②）；
               ③ 离线且**无缓存** → 整页提示同 ② 文案（**不冒充"未填写"**）；
        高风险确认 → **N/A**（SC-16 ⑮ 明确「无」）；
        提交防重 → **N/A**（本页无写操作；写操作在 SC-17）。
    -->
    <view class="pf">
        <view class="pf__body">
            <view class="pf__inner">
                <!-- 离线只读标记（命中缓存 → 带更新时间；未命中 → 说明无本地缓存） -->
                <view v-if="offlineBarText" class="pf__block">
                    <AppOfflineBar variant="offline" :text="offlineBarText" />
                </view>

                <!-- 网络恢复横幅（3s 后自行撤下，DESIGN.md §8.2 C-17） -->
                <view v-if="restoredVisible" class="pf__block">
                    <AppOfflineBar variant="restored" text="网络已恢复，正在刷新" />
                </view>

                <!--
                  ① 编辑入口 → SC-17（A 类页导航栏放不下 ⇒ 照 SC-12 / SC-14 先例落内容区顶部，右对齐）
                  ★ 为什么用外层容器接管点击：离线时需要「置灰**但仍然给提示**」。
                    `AppButton` 的 disabled 会拦掉自身 tap（组件 §八态 disabled 口径），
                    故把点击交给外层容器，内层只负责视觉 —— 与 SC-12「新建目标」同一处置。
                -->
                <view class="pf__top">
                    <view
                        class="pf__edit"
                        :class="{ 'pf__edit--off': offline }"
                        hover-class="pf__edit--press"
                        :hover-start-time="0"
                        :hover-stay-time="80"
                        @tap="onEdit"
                    >
                        <text class="pf__edit-text" :class="{ 'pf__edit-text--off': offline }">编辑档案</text>
                    </view>
                </view>

                <!--
                  ⑭③ 离线且无任何缓存：如实说明不可查看，**不冒充「未填写」**。
                  ★ 必须排在骨架屏**之前**：离线失败时页面态可能仍停在 loading，
                    若让骨架屏优先，用户会看到一片永远加载不出来的灰块。
                -->
                <view v-if="offline && !hasData" class="pf__block">
                    <AppEmpty
                        variant="common"
                        :text="offlineViewText"
                        :show-action="false"
                    />
                </view>

                <!-- ⑪ 加载态：分区骨架屏 -->
                <view v-else-if="state === 'loading'" class="pf__block">
                    <AppSkeleton variant="profile" />
                </view>

                <!-- ⑫ 错误态（整页失败；局部失败不适用 —— 本页只有一组主数据） -->
                <view v-else-if="state === 'error'" class="pf__block">
                    <AppErrorState variant="full" :text="errorMsg" @retry="reload" />
                </view>

                <template v-else>
                    <!-- ⑩ 档案尚未完善（`profile_initialized === false`）→ SC-05 -->
                    <AppCard v-if="needSetup" class="pf__block">
                        <text class="pf__setup-text">档案尚未完善</text>
                        <view
                            class="pf__setup-action"
                            hover-class="pf__setup-action--press"
                            :hover-start-time="0"
                            :hover-stay-time="80"
                            @tap="onSetup"
                        >
                            <text class="pf__setup-action-text">去完善</text>
                        </view>
                    </AppCard>

                    <!-- ② 基础信息块 -->
                    <AppCard class="pf__block" title="基础信息">
                        <AppListRow title="昵称" :value="rows.nickname" />
                        <AppListRow title="性别" :value="rows.gender" />
                        <AppListRow title="出生日期" :value="rows.birth" />
                        <AppListRow title="身高" :value="rows.height" :last="true" />
                    </AppCard>

                    <!-- ③ 身体基础值块（**目标体重只读 + 跳 SC-12**，D-1） -->
                    <AppCard class="pf__block" title="身体基础值">
                        <AppListRow title="初始体重" :value="rows.weight" />
                        <AppListRow
                            title="目标体重"
                            :value="targetWeightText"
                            arrow
                            @tap="onGoalEntry"
                        />
                        <AppListRow title="血型" :value="rows.blood" :last="true" />
                    </AppCard>

                    <!-- ④ 健康背景块（F-062）—— 只回显用户原文，零解读 -->
                    <AppCard class="pf__block" title="健康背景">
                        <template v-if="backgroundVisible">
                            <text class="pf__label">既往病史</text>
                            <text class="pf__text">{{ rows.medical }}</text>
                            <text class="pf__label pf__label--gap">过敏史</text>
                            <text class="pf__text">{{ rows.allergy }}</text>
                            <text class="pf__label pf__label--gap">长期用药记录</text>
                            <text class="pf__text">{{ rows.medication }}</text>
                            <text class="pf__note">
                                以上内容由你自行填写，本应用仅作记录，不做任何解读
                            </text>
                        </template>
                        <!-- ⑭② 健康背景三字段默认不缓存 ⇒ 离线时不展示（避免用旧值冒充当前值） -->
                        <text v-else class="pf__text-offline">{{ offlineViewText }}</text>
                    </AppCard>

                    <!-- ⑥ 页脚注（D-1 标记：目标体重唯一数据源 = 健康目标） -->
                    <text class="pf__foot">
                        目标体重以「健康目标」中的设置为准；本页只读展示，如需修改请前往目标页。
                    </text>
                </template>
            </view>
        </view>

        <!-- 轻提示宿主（离线提示 / 会话失效提示由统一请求层经此渲染） -->
        <AppToast />

        <!-- 开发环境页面预览器（仅 H5 非生产环境渲染；生产构建下为空节点） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppListRow from '../../components/AppListRow.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppEmpty from '../../components/AppEmpty.vue'
import AppToast from '../../components/AppToast.vue'
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { ROUTES, navigateTo, reLaunch, requireLogin } from '../../utils/route'
import { getProfile } from '../../api/profile'
import { fetchGoals } from '../../api/goals'
import { loadCache, saveCache } from '../../utils/cache'
import { useUserStore } from '../../store/user'
import { errorText } from '../../utils/request'
import { showToast } from '../../utils/toast'
import { NETWORK_BANNER_MS } from '../../utils/config'
import { todayString } from '../../utils/validate'

/**
 * 档案离线缓存键（`kj:cache.profile`）。
 * ★★ **待登记（S3-7 上报 G-8）**：按 `utils/cache.js` 的约定「新增业务缓存**必须先登记进
 *    `CACHE_KEYS`**」；但该文件属 **S3-5 封板资产**，本批**未获授权修改** ⇒ 本页暂以本地常量承载。
 *    运行时行为与登记后**完全一致**：`loadCache` / `saveCache` 接受任意 `kj:cache.*` 键，
 *    且 `cache.` 前缀已登记在 `utils/storage.js` 的 `AUTH_SCOPED_PREFIXES`（随四触发自动清除）。
 *    已作为「+1 行授权项（`CACHE_KEYS.PROFILE`）」在 S3-7 第 2 步开发报告中上报，等裁定后归位。
 */
const PROFILE_CACHE_KEY = 'cache.profile'

/** 未填写字段的统一文案（S1-C SC-16 ⑤：**不得**写「未建档」） */
const NOT_FILLED = '未填写'

/** 目标体重「尚未设置」文案（区别于「未填写」：前者是目标模块为空，后者是档案字段为空） */
const TARGET_UNSET = '未设置'

/** 目标体重不可用占位（G-01 辅助请求失败；与 C-21 同先例，静默显示 `—`） */
const TARGET_UNKNOWN = '—'

/** 离线不可查看的统一文案（S1-C SC-16 ⑭② 固定文案，不得改写） */
const OFFLINE_VIEW_TEXT = '离线状态暂不可查看，请联网后查看'

/** 血型值 → 展示文案（**不回显 `UNKNOWN` 原始枚举值**；R-08 字典不含血型 ⇒ 前端常量，同 SC-05 先例） */
const BLOOD_LABEL = {
    A: 'A 型',
    B: 'B 型',
    AB: 'AB 型',
    O: 'O 型',
    UNKNOWN: '不详'
}

/** 性别值 → 展示文案（与 SC-05 `genderOptions` 同口径：1 男 / 2 女） */
const GENDER_LABEL = { 1: '男', 2: '女' }

/** 数值字段 → 展示文案（保留原值，不四舍五入、不补单位以外的修饰） */
function numberText(value, unit) {
    if (value === null || value === undefined || value === '') {
        return NOT_FILLED
    }
    return String(value) + ' ' + unit
}

/** 文本字段 → 展示文案（空 → 「未填写」；**原样输出，不裁剪、不解读**） */
function textText(value) {
    const v = value === null || value === undefined ? '' : String(value)
    return v ? v : NOT_FILLED
}

/** 出生日期 → `YYYY-MM-DD（N 岁）`（S1-C SC-16 ②：展示年龄计算值） */
function birthText(value) {
    const v = value === null || value === undefined ? '' : String(value)
    if (!v) {
        return NOT_FILLED
    }
    const age = ageOf(v)
    return age === null ? v : v + '（' + age + ' 岁）'
}

/** 由 `YYYY-MM-DD` 计算周岁（本地墙上时间口径，S1-D D-4；出生日期晚于今天时返回 null） */
function ageOf(birthDate) {
    const parts = String(birthDate).split('-')
    if (parts.length !== 3) {
        return null
    }
    const y = Number(parts[0])
    const m = Number(parts[1])
    const d = Number(parts[2])
    if (isNaN(y) || isNaN(m) || isNaN(d)) {
        return null
    }
    const today = todayString().split('-')
    const ty = Number(today[0])
    const tm = Number(today[1])
    const td = Number(today[2])
    let age = ty - y
    if (tm < m || (tm === m && td < d)) {
        age = age - 1
    }
    // 越界（未出生 / 超 150 岁）→ 不显示年龄，只显示原始日期（不猜、不报错）
    if (age < 0 || age > 150) {
        return null
    }
    return age
}

/**
 * 从 G-01 响应中取「目标体重」。
 * ★ D-1：目标体重唯一数据源 = `health_goal`，本页**只读**取用，不新建第二数据源。
 * @returns {{known: boolean, value: (number|null), unit: string}} known=false 表示本次未能取得（请求失败）
 */
function weightTargetOf(res) {
    const items = (res && res.data && res.data.items) || []
    for (let i = 0; i < items.length; i++) {
        const g = items[i]
        if (g && g.goal_type === 'weight' && g.target_value !== null && g.target_value !== undefined) {
            return { known: true, value: g.target_value, unit: g.unit ? String(g.unit) : 'kg' }
        }
    }
    return { known: true, value: null, unit: '' }
}

export default {
    components: {
        AppCard: AppCard,
        AppListRow: AppListRow,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState,
        AppOfflineBar: AppOfflineBar,
        AppEmpty: AppEmpty,
        AppToast: AppToast,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /** 页面态：loading / normal / error（离线只影响数据来源，不是独立页面态） */
            state: 'loading',
            /** 档案对象（**离线时来自缓存**，其中健康背景三字段恒为 null） */
            profile: null,
            /** 目标体重：{ known, value, unit } */
            target: { known: true, value: null, unit: '' },
            /** 是否已建档（`profile_initialized === false` → 「档案尚未完善」） */
            needSetup: false,
            /** 失败文案（取自统一请求层，不自行编造） */
            errorMsg: '',

            /* ── 离线 / 网络 ── */
            offline: false,
            /** 当前展示来自本地缓存的写入时刻（用于「离线数据 · 更新于 <时间>」） */
            cacheSavedAt: '',
            restoredVisible: false,

            /** 本次 onShow 之前是否已加载过（避免与 onLoad 双发） */
            entered: false,
            /** 请求序号（并发保护：过期响应直接丢弃） */
            reqToken: 0,
            bannerTimer: null,
            networkHandler: null
        }
    },
    computed: {
        /** 有可展示的档案数据（离线且未命中缓存 → false） */
        hasData: function () {
            return !!this.profile
        },
        /** 健康背景是否可见（⑭②：默认不缓存 ⇒ 离线时不可见） */
        backgroundVisible: function () {
            return !this.offline
        },
        /** 离线条文案：命中缓存 → 带更新时间；未命中 → 说明当前无本地缓存 */
        offlineBarText: function () {
            if (!this.offline) {
                return ''
            }
            if (this.cacheSavedAt) {
                return '离线数据 · 更新于 ' + this.cacheSavedAt
            }
            return '当前离线，暂无本地缓存数据'
        },
        /** 离线不可查看的统一文案（S1-C SC-16 ⑭② 固定文案；健康背景与整页无缓存两种场景共用） */
        offlineViewText: function () {
            return OFFLINE_VIEW_TEXT
        },
        /** 目标体重展示文案（三态：具体值 / 「未设置」/ 「—」） */
        targetWeightText: function () {
            const t = this.target || {}
            if (!t.known) {
                return TARGET_UNKNOWN
            }
            if (t.value === null || t.value === undefined) {
                return TARGET_UNSET
            }
            return String(t.value) + ' ' + (t.unit ? String(t.unit) : 'kg')
        },
        /** 回显行（**只做格式化，不做任何判断或解读**） */
        rows: function () {
            const p = this.profile || {}
            return {
                nickname: textText(p.nickname),
                gender: GENDER_LABEL[p.gender] ? GENDER_LABEL[p.gender] : NOT_FILLED,
                birth: birthText(p.birth_date),
                height: numberText(p.height_cm, 'cm'),
                weight: numberText(p.initial_weight_kg, 'kg'),
                blood: BLOOD_LABEL[p.blood_type] ? BLOOD_LABEL[p.blood_type] : NOT_FILLED,
                medical: textText(p.medical_history),
                allergy: textText(p.allergy_history),
                medication: textText(p.medication_notes)
            }
        }
    },
    onLoad: function () {
        // 未登录守卫（S1-C SC-16 ⑬：需登录）
        if (!requireLogin()) {
            return
        }
        const store = useUserStore()
        store.hydrate()
        this.needSetup = store.profileInitialized === false

        this.load(false)

        // 网络恢复 → 自动刷新本页（只读页，**不自动重放**任何写操作）
        const self = this
        this.networkHandler = function (res) {
            self.handleNetworkChange(res)
        }
        uni.onNetworkStatusChange(this.networkHandler)
    },
    onShow: function () {
        // SC-16 ⑯：从 SC-17 返回后**自动刷新**（DESIGN.md §7④）；首次进入由 onLoad 负责，避免双发
        if (this.entered) {
            const store = useUserStore()
            store.hydrate()
            this.needSetup = store.profileInitialized === false
            this.load(true)
        }
        this.entered = true
    },
    onUnload: function () {
        this.clearBanner()
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
    },
    methods: {
        /* ───────────── 数据加载 ───────────── */

        /**
         * 加载 P-01（主）+ G-01（辅）。
         * @param {boolean} silent 静默刷新（返回本页 / 网络恢复）：不显示骨架，避免打断阅读
         */
        load: function (silent) {
            const self = this
            this.reqToken += 1
            const token = this.reqToken
            this.errorMsg = ''

            // 先读本地缓存：命中 → 立即只读渲染（离线可看的基础），再向服务端刷新
            if (!silent) {
                const cached = loadCache(PROFILE_CACHE_KEY)
                if (cached && cached.data && cached.data.profile) {
                    this.commit(cached.data.profile, cached.data.target, cached.savedAt, true)
                } else if (!this.profile) {
                    this.state = 'loading'
                }
            }

            // G-01 降级为「永不 reject」的辅助请求：失败时目标体重显示「—」，不影响主数据
            const goalsPromise = fetchGoals().then(function (res) {
                return { ok: true, res: res }
            }, function () {
                return { ok: false, res: null }
            })

            return Promise.all([getProfile(), goalsPromise]).then(function (out) {
                // 过期响应（页面已重新加载）→ 丢弃，由最新一次请求收尾
                if (token !== self.reqToken) {
                    return
                }
                const profile = (out[0] && out[0].data && out[0].data.profile) || {}
                const goalsOut = out[1]
                const target = goalsOut.ok
                    ? weightTargetOf(goalsOut.res)
                    : { known: false, value: null, unit: '' }
                self.offline = false
                const savedAt = self.saveAndStamp(profile, target)
                self.commit(profile, target, savedAt, false)
            }, function (err) {
                if (token !== self.reqToken) {
                    return
                }
                if (err && err.isNetwork) {
                    // ★ 401 / 会话失效**不会**走到这里（统一请求层已处理并清栈回 SC-03），
                    //   因此 isNetwork 就是真离线 —— 不能把 401 当成「档案为空」（会谎报「未填写」）。
                    self.offline = true
                    // 命中缓存 → 保持只读展示（离线条已说明数据来源与时间）；未命中 → hasData=false 分支
                    return
                }
                self.errorMsg = errorText(err)
                self.state = 'error'
            })
        },

        /** 手动重试（失败组件的重试入口）：按「首次加载」处理，避免继续停留在失败态 */
        reload: function () {
            this.offline = false
            this.load(false)
        },

        /**
         * 落地一次渲染（**原子替换**）。
         * 调用前置：`profile` 必为对象（P-01 对未建档用户返回全 null 对象而非 404；
         * 缓存路径亦有 `cached.data.profile` 守卫）⇒ 本方法只处理「有数据」这一种情形。
         * @param {object} profile 档案对象
         * @param {object} target 目标体重 { known, value, unit }
         * @param {string} savedAt 缓存写入时刻（空串 = 非缓存来源）
         * @param {boolean} fromCache 本次是否来自本地缓存
         */
        commit: function (profile, target, savedAt, fromCache) {
            this.profile = profile || null
            if (target && target.known !== undefined) {
                this.target = target
            } else if (fromCache) {
                // 缓存信封里没有目标体重（异常载荷）→ 按「未设置」处理，不猜、不编造
                this.target = { known: true, value: null, unit: '' }
            }
            this.state = 'normal'
            this.cacheSavedAt = fromCache ? (savedAt || '') : ''
        },

        /**
         * 写缓存并回读写入时刻。
         * ★ **刻意剔除健康背景三字段**（`medical_history` / `allergy_history` / `medication_notes`）——
         *   S1-C SC-16 ⑭② 明确「健康背景三字段默认不缓存」，且 ⑭② 要求离线时显示
         *   「离线状态暂不可查看，请联网后查看」。若把这三段原文写进本地缓存，
         *   离线时会用旧值冒充当前值 —— 属**展示不实数据**。
         */
        saveAndStamp: function (profile, target) {
            const slim = {
                nickname: profile.nickname,
                gender: profile.gender,
                birth_date: profile.birth_date,
                height_cm: profile.height_cm,
                initial_weight_kg: profile.initial_weight_kg,
                blood_type: profile.blood_type
            }
            if (!saveCache(PROFILE_CACHE_KEY, { profile: slim, target: target })) {
                return ''
            }
            const back = loadCache(PROFILE_CACHE_KEY)
            return back ? back.savedAt : ''
        },

        /* ───────────── 出口 ───────────── */

        /** 【编辑档案】→ SC-17；**离线禁止编辑**（不进入编辑态，仅给中性提示 —— SC-17 ⑭） */
        onEdit: function () {
            if (this.offline) {
                showToast('info', '离线状态暂不可编辑')
                return
            }
            navigateTo(ROUTES.PROFILE_EDIT)
        },

        /** 【目标体重】→ SC-12 目标页（D-1：编辑入口只在 SC-13 / SC-12 链路） */
        onGoalEntry: function () {
            navigateTo(ROUTES.GOAL)
        },

        /** 「去完善」→ SC-05 建档引导（清栈，避免回退到不完整的档案页） */
        onSetup: function () {
            reLaunch(ROUTES.PROFILE_SETUP)
        },

        /* ───────────── 网络状态 ───────────── */

        handleNetworkChange: function (res) {
            const online = !!(res && res.isConnected)
            if (!online) {
                this.offline = true
                return
            }
            this.offline = false
            this.showRestoredBanner()
            this.load(true)
        },

        showRestoredBanner: function () {
            const self = this
            this.clearBanner()
            this.restoredVisible = true
            this.bannerTimer = setTimeout(function () {
                self.restoredVisible = false
                self.bannerTimer = null
            }, NETWORK_BANNER_MS)
        },

        clearBanner: function () {
            if (this.bannerTimer) {
                clearTimeout(this.bannerTimer)
                this.bannerTimer = null
            }
        }
    }
}
</script>

<style scoped lang="scss">
.pf {
    min-height: 100vh;
    background-color: var(--s-page);
}

/* A 类系统导航栏占位由平台负责，此处只留内容区节奏 */
.pf__body {
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

/* 内容最大宽居中（DESIGN.md §10.4③）+ 唯一水平边距来源 --gutter */
.pf__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.pf__block {
    margin-bottom: var(--card-gap);
}

/* ── ① 编辑入口（内容区顶部右对齐） ── */
.pf__top {
    display: flex;
    flex-direction: row;
    justify-content: flex-end;
    margin-bottom: var(--card-gap);
}

.pf__edit {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-height: var(--tap-min);
    padding-left: var(--sp-5);
    padding-right: var(--sp-5);
    border: 1rpx solid var(--b-border);
    border-radius: var(--r-sm);
    background-color: var(--s-card);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.pf__edit--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

/* 离线：置灰（点击仍由外层容器接管 → 给中性提示，而不是"点了没反应"） */
.pf__edit--off {
    background-color: var(--s-sunken);
    border: 1rpx solid var(--s-sunken);
}

.pf__edit-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--t-link);
    letter-spacing: 0;
}

.pf__edit-text--off {
    color: var(--t-4);
}

/* ── ⑩ 档案尚未完善 ── */
.pf__setup-text {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-2);
    letter-spacing: 0;
}

.pf__setup-action {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    align-self: flex-start;
    min-height: var(--tap-min);
    margin-top: var(--sp-4);
    padding-left: var(--sp-5);
    padding-right: var(--sp-5);
    border-radius: var(--r-sm);
    background-color: var(--s-brand-soft);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.pf__setup-action--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.pf__setup-action-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--c-p-600);
    letter-spacing: 0;
}

/* ── ④ 健康背景文本块（**只回显原文**） ── */
.pf__label {
    display: block;
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.pf__label--gap {
    margin-top: var(--sp-6);
}

.pf__text {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-1);
    letter-spacing: 0;
    word-break: break-all;
}

.pf__text-offline {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-3);
    letter-spacing: 0;
}

.pf__note {
    display: block;
    margin-top: var(--sp-6);
    padding-top: var(--sp-4);
    border-top: 1rpx solid var(--b-line);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── ⑥ 页脚注（D-1 标记） ── */
.pf__foot {
    display: block;
    padding: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
