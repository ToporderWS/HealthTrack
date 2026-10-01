<template>
    <!--
      SC-22 数据删除页（pages/data/delete）
      依据：S1-C §二 SC-22（结构 / 区分说明行 / ⑨~⑰ 状态与接口）｜S1-C-UIUX §6.4「高风险操作的视觉与交互区分（强制）」
            ｜DESIGN.md §2.3（令牌登记用途）/ §8（C-01/C-03/C-06/C-08/C-12/C-14/C-17/C-19/C-20）/ §11 / §12 / §13
      顶栏：**A 类系统导航栏**（DESIGN.md §10.3：B 类自绘顶栏名单不含 SC-22）——
            标题「数据删除」由 `pages.json` 在**子项 3.4 接线**时指定；本页**不调用** `uni.setNavigationBarTitle`
            （未接线前无页面对应，自行设标题会产生两份真相）。

      结构（与 S1-C 逐项对应）：
        [① 顶部栏] 系统导航栏
        【区块 A · 批量删除】（F-072）
          ├─ 指标选择（多选 / 单指标）—— **B-1 裁定**：C-20 `#tail` 槽 + C-19 `AppSwitch`，**不新增组件编号**
          │    ★ 行本身 `arrow = false` ⇒ `tapEnabled = !disabled && arrow = false` ⇒ 组件**不派发 `tap`**：
          │      不出现"假入口"箭头，开关是唯一交互点（C-20 的 switch 变体未实现，见其头注）
          ├─ 时间范围（近 7 / 30 / 90 / 自定义，**半开区间**）—— C-08 `AppSegmented` + C-06 `AppDatePicker`×2
          │    ★ 与 SC-10 完全同先例：请求严格用 `[start, end)`；「近 N 天」= `[今天−(N−1), 明天)`；
          │      自定义 `end` = 「结束日期 **+1 天**」的 `YYYY-MM-DD`，**绝不拼 23:59:59**
          ├─ [预览条数]「将删除 N 条记录」—— `R-07`（只读）；统计中显示「统计中…」
          ├─ [删除按钮] —— `R-06`（破坏性写）：① 验密弹窗 ② 二次确认弹窗「删除后无法恢复」
          │                  ③ 若 N ≥ 500：追加输入文本「确认删除」→ Toast「已删除 N 条」
          └─ 空状态：「当前范围内没有可删除的记录」+ 删除按钮置灰
        【区块 B · 清空全部数据】（F-073，**红色强提示**）—— `D-02`（破坏性写）
          红色警示框 + 后果清单（4 类）+「账号会被保留；此操作不注销账号」
          + 输入「确认删除」+ 输入登录密码 + [清空全部数据]（红色）
          → Toast「已清除 N 条记录；账号保留，数据已按规则清除」+ **同步清除本地健康数据缓存**
        [② 与「注销账号」的区分说明行]「若你希望连账号一并注销，请前往 **我的 → 注销账号**」
          （**仅文字指引、不含任何跳转按钮**）

      ★★ 三条硬口径（本页安全边界，验收必看）：
        ① **本页只清数据、保留账号**：界面与请求体**均不出现**「注销」「删除账号」作为可选项，
           也**不接受任何"一并删档案 / 账号"参数**（`D-02` 契约未定义 `include_profile_row` / `delete_account`）；
        ② **「30 天」只作后台机制**：本页用户可见表述**只有**「删除后无法恢复」——
           **界面文案与脚本字符串中均不出现「30 天」**（S3-8 预检 §六 红线；本文件内该词只出现在本注释中，
           静态自检按「剥注释后判定」口径检查）；
        ③ **必须在线**：离线时两区块按钮全部置灰 + 提示「当前网络不可用」，
           **离线不得进入验密流程**（`canAskDelete` / `canClear` 均先判 `offline`）。

      ★ 危险色口径（**与冻结令牌登记一致，见交付报告 §五**）：S1-C §6.4 表把「批量删除」写作「警示橙」，
        但 `DESIGN.md §2.3` 对 `--c-warning` 的**登记用途**仅「软提示 / 权限未开 / 提醒未生效」，
        **不含危险操作**；而 `--c-danger` 的登记用途含「**危险操作警示**」。
        ⇒ 本页区块 A、区块 B 的按钮统一用 `--c-danger`（`AppButton type="danger"`），
        **不越出令牌登记用途、也不页内自绘按钮**（C-01 无 warning 变体，属已封板基座、不在本批授权内）；
        两区块的**严重度阶梯**改由「红色警示框 + 后果清单 + 双重输入」承担（与 DESIGN.md §13 高风险行一致）。

      状态覆盖（S1-C ⑨~⑰ 逐项映射）：
        正常 ✅ 选范围 → 预览 N → 验密 → 二次确认 → 执行 → Toast
        空态 ✅ 「当前范围内没有可删除的记录」+ 删除按钮置灰
        加载 ✅ 预览「统计中…」；执行时按钮 loading（`AppButton` 内置 + `disabled` ⇒ 不可重复点击）
        失败 ✅ `COUNT_MISMATCH` → 「数据已变化，请刷新后重试」+ **刷新入口 = 重新点「预览条数」**（旧条数已作废、删除按钮置灰），**不执行删除**
              密码错 → 「密码不正确」（验密弹窗内联提示）；其他失败 → 「删除失败，请重试」+ 数据保持原状
        未登录 ✅ 守卫 → SC-03
        离线 ✅ 离线条 + 两区块按钮置灰；**不进入验密流程**；离线仍可改范围 / 指标（纯本地筛选、无副作用）
        401 ✅ 统一请求层（单次 refresh + replay；失败清栈回 SC-03）
        提交防重 ✅ 执行中 `executing = true` ⇒ 按钮 `loading + disabled`
        高风险确认 ✅ 区块 A：验密 + 二次确认（≥500 追加文本）；区块 B：红色强提示 + 文本 + 密码（**双重，无倒计时**）

      ★ 返回拦截铁律（S3-2 实测，必须遵守）：本页**不实现 `onBackPress`** ——
        返回箭头走系统导航栏、无需自绘返回；未写该钩子即不存在"自我拦截 → `navigateBack:fail`"风险。

      ★ 未接线（**如实登记**，非漏做）：`pages.json` / `utils/route.js` / `DevPagePreviewer` /
        `pages/mine/index.vue` 的注册与入口放开属**子项 3.4**，本子项**未改一行** ⇒
        本页当前**不可 URL 直达**，故本子项**无 H5 端到端验证**（与子项 3.1 同口径）。
    -->
    <view class="dpage">
        <view class="dpage__body">
            <view class="dpage__inner">
                <!-- ⑭ 离线标记条（文案逐字取自 S1-C SC-22 ⑭；本页无缓存可读，故不带"更新于"） -->
                <view v-if="offline" class="dpage__block">
                    <AppOfflineBar variant="offline" text="当前网络不可用" />
                </view>

                <!-- 网络恢复横幅（3s 后自行撤下，DESIGN.md §8.2 C-17） -->
                <view v-if="restoredVisible" class="dpage__block">
                    <AppOfflineBar variant="restored" text="网络已恢复" />
                </view>

                <!-- ══════════ 区块 A · 批量删除（F-072） ══════════ -->
                <view class="dpage__block">
                    <AppCard title="批量删除">
                        <!-- 指标选择（多选；默认全选 8 类 ⇒ 等价于"不限指标"） -->
                        <AppListRow
                            v-for="(row, index) in metricRows"
                            :key="row.type"
                            :icon="row.icon"
                            :title="row.title"
                            :last="index === metricRows.length - 1"
                        >
                            <template #tail>
                                <AppSwitch
                                    :model-value="row.checked"
                                    @change="onToggleMetric(row.type)"
                                />
                            </template>
                        </AppListRow>

                        <!-- 一个都没选时给出说明（置灰的按钮必须说明原因，**不静默无反应**） -->
                        <text v-if="selectionHint" class="dpage__hint">{{ selectionHint }}</text>

                        <!-- 时间范围（C-08 四段；「自定义」开抽屉，与 SC-10 同先例） -->
                        <view class="dpage__range">
                            <AppSegmented
                                :model-value="rangeMode"
                                :options="rangeOptions"
                                :disabled="executing"
                                @change="onRangeChange"
                            />
                        </view>

                        <!-- [预览条数]（R-07）：统计中 / 结果 / 错误 三态互斥 -->
                        <view class="dpage__preview">
                            <AppButton
                                label="预览条数"
                                type="secondary"
                                size="m"
                                :disabled="previewDisabled"
                                :loading="previewing"
                                @tap="onPreview"
                            />
                            <text
                                class="dpage__preview-text"
                                :class="{ 'dpage__preview-text--error': !!previewError }"
                            >{{ previewText }}</text>
                        </view>

                        <!-- [删除按钮]（R-06 → 验密 → 二次确认；危险色 = --c-danger，§2.3 登记用途"危险操作警示"） -->
                        <view class="dpage__action">
                            <AppButton
                                label="删除所选记录"
                                type="danger"
                                block
                                :disabled="deleteDisabled"
                                :loading="executing"
                                @tap="onAskDelete"
                            />
                        </view>
                    </AppCard>
                </view>

                <!-- ══════════ 区块 B · 清空全部数据（F-073，红色强提示） ══════════ -->
                <view class="dpage__block">
                    <AppCard title="清空全部数据">
                        <!-- 红色警示框 + 后果清单（逐字取自 S1-C SC-22 区块 B） -->
                        <view class="dpage__danger-box">
                            <text class="dpage__danger-title">删除后无法恢复，将清除以下数据</text>
                            <view
                                v-for="(item, index) in clearScopeItems"
                                :key="index"
                                class="dpage__danger-item"
                            >
                                <text class="dpage__danger-mark">·</text>
                                <text class="dpage__danger-text">{{ item }}</text>
                            </view>
                            <text class="dpage__danger-note">账号会被保留；此操作不注销账号</text>
                        </view>

                        <!-- 双重确认（**无倒计时**）：输入文本 + 输入登录密码；两者齐备前按钮置灰 -->
                        <view class="dpage__field">
                            <AppInput
                                v-model="clearText"
                                label="确认文字"
                                placeholder="请输入「确认删除」"
                                :maxlength="20"
                                :disabled="clearing"
                            />
                        </view>
                        <view class="dpage__field">
                            <AppInput
                                v-model="clearPassword"
                                label="登录密码"
                                placeholder="请输入登录密码"
                                password
                                :maxlength="64"
                                :disabled="clearing"
                                :error="clearError"
                            />
                        </view>

                        <view class="dpage__action">
                            <AppButton
                                label="清空全部数据"
                                type="danger"
                                block
                                :disabled="clearDisabled"
                                :loading="clearing"
                                @tap="onClearAll"
                            />
                        </view>
                    </AppCard>
                </view>

                <!-- [② 与「注销账号」的区分说明行]（**仅文字指引、无跳转按钮**；出口仍由 SC-18 承载） -->
                <text class="dpage__distinct-text">若你希望连账号一并注销，请前往 <text class="dpage__distinct-strong">我的 → 注销账号</text></text>
            </view>
        </view>

        <!-- ① 验密弹窗（C-12 `mode="danger"`：不可点遮罩关闭；S1-C ⑧「验密弹窗（G7 变体）」） -->
        <AppModal
            :show="pwdVisible"
            mode="danger"
            title="验证登录密码"
            confirm-text="下一步"
            cancel-text="取消"
            :confirm-disabled="!pwdValue"
            @confirm="onPwdConfirm"
            @cancel="onPwdCancel"
        >
            <view class="dpage__modal-text">为确认是本人操作，删除前需验证当前账号的登录密码。</view>
            <view class="dpage__field">
                <AppInput
                    v-model="pwdValue"
                    label="登录密码"
                    placeholder="请输入登录密码"
                    password
                    :maxlength="64"
                    :error="pwdError"
                />
            </view>
        </AppModal>

        <!-- ② 二次确认弹窗（C-12 `mode="danger"`；N ≥ 500 时**追加**输入文本「确认删除」） -->
        <AppModal
            :show="confirmVisible"
            mode="danger"
            title="删除后无法恢复"
            confirm-text="确认删除"
            cancel-text="取消"
            @confirm="onConfirmDelete"
            @cancel="onConfirmCancel"
        >
            <view class="dpage__modal-text">{{ confirmSummary }}</view>
            <view v-if="needConfirmText" class="dpage__field">
                <AppInput
                    v-model="confirmText"
                    label="确认文字"
                    placeholder="请输入「确认删除」"
                    :maxlength="20"
                    :error="confirmError"
                />
            </view>
        </AppModal>

        <!-- 自定义时间范围（C-12 抽屉 + 两把 C-06 日期选择器，**不新增范围组件**） -->
        <AppModal
            :show="rangeVisible"
            title="自定义时间范围"
            confirm-text="确定"
            cancel-text="取消"
            @confirm="onRangeConfirm"
            @cancel="onRangeCancel"
        >
            <view class="dpage__field">
                <AppDatePicker
                    v-model="draftStart"
                    mode="date"
                    label="开始日期"
                    placeholder="请选择开始日期"
                    :end="today"
                />
            </view>
            <view class="dpage__field">
                <AppDatePicker
                    v-model="draftEnd"
                    mode="date"
                    label="结束日期"
                    placeholder="请选择结束日期"
                    :end="today"
                />
            </view>
            <text class="dpage__hint">按所选日期范围统计（含首尾两天）</text>
        </AppModal>

        <!-- 轻提示宿主（成功 / 失败 / 会话失效提示经此渲染） -->
        <AppToast />

        <!-- 开发期页面预览入口（第 22 项 SC-22 的 ready 开关属子项 3.4） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppListRow from '../../components/AppListRow.vue'
import AppSwitch from '../../components/AppSwitch.vue'
import AppSegmented from '../../components/AppSegmented.vue'
import AppDatePicker from '../../components/AppDatePicker.vue'
import AppModal from '../../components/AppModal.vue'
import AppInput from '../../components/AppInput.vue'
import AppButton from '../../components/AppButton.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppToast from '../../components/AppToast.vue'
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { requireLogin } from '../../utils/route'
import { showToast } from '../../utils/toast'
import { errorText, newIdempotencyKey } from '../../utils/request'
import { isOnline } from '../../utils/network'
import { listKeys, removeRaw } from '../../utils/storage'
import { cancelAllRegistered } from '../../utils/notify'
import { METRIC_TYPES, metricLabel } from '../../utils/metrics'
import { NETWORK_BANNER_MS } from '../../utils/config'
import { countRecords, batchDeleteRecords } from '../../api/records'
import { clearAllData } from '../../api/data'

/** 时间范围默认值（近 30 天；与 SC-10 默认值、缓存保留窗口一致） */
const DEFAULT_RANGE = '30'

/** 时间范围四段（C-08；顺序即展示顺序） */
const RANGE_OPTIONS = [
    { value: '7', label: '近 7 天' },
    { value: '30', label: '近 30 天' },
    { value: '90', label: '近 90 天' },
    { value: 'custom', label: '自定义' }
]

/**
 * 大数量二次确认阈值 —— 与后端 `record_service.CONFIRM_THRESHOLD` **同值**（500）。
 * ★ 服务端按**实际条数**判定，前端按**预览条数**预判 ⇒ 前端只负责"提前把输入框亮出来"，
 *   最终闸门仍在服务端（实际条数 ≥ 500 且 `confirm_text` 不符 → `422`）。
 */
const CONFIRM_THRESHOLD = 500

/** 确认文字 —— 与后端 `record_service.CONFIRM_TEXT` / `data_service.CONFIRM_TEXT` **逐字同值** */
const CONFIRM_TEXT = '确认删除'

/** 区块 B 后果清单（S1-C SC-22 区块 B 逐字，顺序冻结，**不增删类别**） */
const CLEAR_SCOPE_ITEMS = [
    '全部健康记录（8 类）',
    '全部健康目标',
    '全部提醒（本地）',
    '档案中的健康数据（身高 / 初始体重 / 血型 / 病史 / 过敏 / 用药文本）'
]

/** 只清「业务缓存」与「本地提醒」两类本地键的前缀（**绝不动 `auth.` / `guide.`**） */
const LOCAL_DATA_PREFIXES = ['cache.', 'reminder.']

/** 两位补零 */
function pad2(value) {
    return value < 10 ? '0' + value : String(value)
}

/** `Date` → `YYYY-MM-DD`（本地墙上时间，S1-D D-4） */
function dayString(date) {
    return String(date.getFullYear()) + '-' + pad2(date.getMonth() + 1) + '-' + pad2(date.getDate())
}

/** 今天 ± N 天的 `YYYY-MM-DD`（N 为负即往前） */
function shiftDay(days) {
    const d = new Date()
    d.setDate(d.getDate() + days)
    return dayString(d)
}

/** `YYYY-MM-DD` 偏移 N 天（把「结束日期」变成半开区间的开区端点） */
function addDays(dayText, days) {
    const parts = String(dayText || '').split('-')
    if (parts.length !== 3) {
        return ''
    }
    const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
    d.setDate(d.getDate() + days)
    return dayString(d)
}

export default {
    components: {
        AppCard: AppCard,
        AppListRow: AppListRow,
        AppSwitch: AppSwitch,
        AppSegmented: AppSegmented,
        AppDatePicker: AppDatePicker,
        AppModal: AppModal,
        AppInput: AppInput,
        AppButton: AppButton,
        AppOfflineBar: AppOfflineBar,
        AppToast: AppToast,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /* ── 区块 A：筛选条件 ── */
            /** 指标多选（**默认全选 8 类**；S-7 先例：全选 = 不限指标，单次调用即可） */
            metricSelection: METRIC_TYPES.slice(),
            /** 时间范围：'7' | '30' | '90' | 'custom' */
            rangeMode: DEFAULT_RANGE,
            /** 自定义范围的**已生效**取值（`YYYY-MM-DD`） */
            customStart: '',
            customEnd: '',
            /** 自定义抽屉的**草稿**值（确认后才生效，取消即丢弃） */
            draftStart: '',
            draftEnd: '',
            rangeVisible: false,

            /* ── 区块 A：预览（R-07）── */
            /** 预览条数（`null` = 尚未预览；`0` = 空态） */
            previewCount: null,
            /** 预览明细（逐目标条数；执行时**按同一组合**逐个删除，不重新推导） */
            previewParts: [],
            previewing: false,
            previewError: '',
            /** 预览序号（筛选条件一变 ⇒ 序号自增 ⇒ 过期响应直接丢弃） */
            previewToken: 0,

            /* ── 区块 A：验密弹窗（R-06 的第 ① 步）── */
            pwdVisible: false,
            pwdValue: '',
            pwdError: '',

            /* ── 区块 A：二次确认弹窗（R-06 的第 ②③ 步）── */
            confirmVisible: false,
            confirmText: '',
            confirmError: '',

            /* ── 写操作执行态（防重复点击）── */
            executing: false,

            /* ── 区块 B：清空全部数据（D-02）── */
            clearText: '',
            clearPassword: '',
            clearError: '',
            clearing: false,

            /* ── 网络 ── */
            offline: false,
            restoredVisible: false,
            networkHandler: null,
            bannerTimer: null,

            /* ── 静态选项（放在 data 里以保持模板取值路径稳定）── */
            rangeOptions: RANGE_OPTIONS,
            clearScopeItems: CLEAR_SCOPE_ITEMS
        }
    },
    computed: {
        /** 指标多选行（顺序 = `METRIC_TYPES` 固定序；8 类均有 C-20 内建几何图标） */
        metricRows: function () {
            const rows = []
            for (let i = 0; i < METRIC_TYPES.length; i++) {
                const type = METRIC_TYPES[i]
                rows.push({
                    type: type,
                    icon: type,
                    title: metricLabel(type),
                    checked: this.metricSelection.indexOf(type) >= 0
                })
            }
            return rows
        },
        /** 一个指标都没选时的说明（唯一交互点是开关，故需要文字解释置灰原因） */
        selectionHint: function () {
            return this.metricSelection.length === 0 ? '请至少选择一个指标' : ''
        },
        /** 今天的 `YYYY-MM-DD`（日期选择器上界：记录不可能发生在未来） */
        today: function () {
            return dayString(new Date())
        },
        /**
         * 请求窗口（**半开区间 `[start, end)`**）。
         *   · 近 N 天（含今天）：`start = 今天−(N−1)`、`end = 明天`；
         *   · 自定义：`start = 开始日期`、`end = 结束日期 + 1 天`（**不拼 23:59:59**）。
         */
        windowRange: function () {
            if (this.rangeMode === 'custom') {
                return {
                    start: this.customStart,
                    end: this.customEnd ? addDays(this.customEnd, 1) : ''
                }
            }
            const days = Number(this.rangeMode) || 30
            return {
                start: shiftDay(1 - days),
                end: shiftDay(1)
            }
        },
        /** 是否已全选 8 类（全选 ⇒ 请求省略 `metric_type`，即"不限指标"） */
        allMetricsSelected: function () {
            return this.metricSelection.length === METRIC_TYPES.length
        },
        /** 是否需要追加输入「确认删除」（**按预览条数预判**，服务端按实际条数复核） */
        needConfirmText: function () {
            return typeof this.previewCount === 'number' && this.previewCount >= CONFIRM_THRESHOLD
        },
        /** 二次确认弹窗正文（逐字复用预览文案，**不另造一套说法**） */
        confirmSummary: function () {
            if (!(this.previewCount > 0)) {
                return ''
            }
            return '将删除 ' + this.previewCount + ' 条记录'
        },
        /** 预览结果文案（⑩ 空态 / ⑪ 统计中 / 正常） */
        previewText: function () {
            if (this.previewing) {
                return '统计中…'
            }
            if (this.previewError) {
                return this.previewError
            }
            if (this.previewCount === null) {
                return ''
            }
            if (this.previewCount <= 0) {
                return '当前范围内没有可删除的记录'
            }
            return '将删除 ' + this.previewCount + ' 条记录'
        },
        /** [预览条数] 是否不可点（离线 / 统计中 / 执行中 / 未选指标） */
        previewDisabled: function () {
            return this.offline || this.previewing || this.executing || this.metricSelection.length === 0
        },
        /** [删除按钮] 是否不可点（离线 / 执行中 / 统计中 / 空态）—— ⑩ 空态置灰、⑭ 离线置灰 */
        deleteDisabled: function () {
            return this.offline || this.executing || this.previewing || !(this.previewCount > 0)
        },
        /** [清空全部数据] 是否不可点（离线 / 执行中 / 确认文字不符 / 密码为空）—— **无倒计时** */
        clearDisabled: function () {
            return this.offline
                || this.clearing
                || this.clearText.trim() !== CONFIRM_TEXT
                || !this.clearPassword
        }
    },
    onLoad: function () {
        // 未登录守卫（S1-C ⑬：需登录）
        if (!requireLogin()) {
            return
        }

        // 本页首个动作（预览）之前就可能有请求，故**进入即判一次网络**
        // （与只读页"靠请求失败反推离线"不同：写操作按钮必须**先**置灰，不能等失败）
        const self = this
        isOnline().then(function (online) {
            self.offline = !online
        })

        // 网络监听（**必须在 onLoad 注册**，S3-2 时序纪律）
        this.networkHandler = function (res) {
            self.handleNetworkChange(res)
        }
        uni.onNetworkStatusChange(this.networkHandler)
    },
    onUnload: function () {
        this.clearBanner()
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
    },
    onHide: function () {
        // 空实现：本页无后台任务、无计时型业务
    },
    methods: {
        /* ───────────── 筛选条件 ───────────── */

        /**
         * 指标开关（唯一交互点）。
         * ★ 任何筛选条件变化都必须**立即作废已预览的条数**（`invalidatePreview`）——
         *   否则用户可能拿"旧范围的 N"去删"新范围的数据"（正确性问题，不只是体验问题）。
         */
        onToggleMetric: function (type) {
            if (this.executing) {
                return
            }
            const next = []
            let removed = false
            for (let i = 0; i < this.metricSelection.length; i++) {
                if (this.metricSelection[i] === type) {
                    removed = true
                } else {
                    next.push(this.metricSelection[i])
                }
            }
            if (!removed) {
                next.push(type)
            }
            this.metricSelection = next
            this.invalidatePreview()
        },
        /** 时间范围切换（「自定义」= 开抽屉的动作 ⇒ **不改变 `rangeMode`**，取消即回原选项） */
        onRangeChange: function (next) {
            if (this.executing) {
                return
            }
            if (next === 'custom') {
                this.draftStart = this.customStart
                this.draftEnd = this.customEnd
                this.rangeVisible = true
                return
            }
            if (next === this.rangeMode) {
                return
            }
            this.rangeMode = next
            this.invalidatePreview()
        },
        onRangeConfirm: function () {
            this.customStart = this.draftStart
            this.customEnd = this.draftEnd
            this.rangeMode = 'custom'
            this.rangeVisible = false
            this.invalidatePreview()
        },
        onRangeCancel: function () {
            this.rangeVisible = false
        },
        /** 作废预览（条件变更 / 失败后重来 / 执行完成）：条数与明细一并清空，按钮随之置灰 */
        invalidatePreview: function () {
            this.previewToken += 1
            this.previewing = false
            this.previewCount = null
            this.previewParts = []
            this.previewError = ''
        },

        /* ───────────── 预览条数（R-07，只读） ───────────── */

        onPreview: function () {
            this.runPreview()
        },
        /**
         * 逐目标统计条数（G-10：`metric_type` 为单值 ⇒ 多选只能逐个请求后求和）。
         * 全选 8 类 ⇒ 单次调用（省略 `metric_type`，服务端按"不限指标"统计）。
         */
        runPreview: function () {
            const self = this
            if (this.metricSelection.length === 0 || this.offline) {
                this.invalidatePreview()
                return Promise.resolve()
            }

            this.previewToken += 1
            const token = this.previewToken
            this.previewing = true
            this.previewError = ''

            const range = this.windowRange
            const targets = this.previewTargets()
            const results = []

            function step(index) {
                if (index >= targets.length) {
                    return Promise.resolve()
                }
                const query = {}
                if (targets[index]) {
                    query.metric_type = targets[index]
                }
                if (range.start) {
                    query.start = range.start
                }
                if (range.end) {
                    query.end = range.end
                }
                return countRecords(query).then(function (res) {
                    const raw = res && res.data ? res.data.count : 0
                    const n = Number(raw)
                    // 非法 / 负数一律按 0 计（**不放大条数**，与"不伪造数据"同口径）
                    results.push({
                        metricType: targets[index],
                        count: isNaN(n) || n < 0 ? 0 : n
                    })
                    return step(index + 1)
                })
            }

            return step(0).then(function () {
                // 过期响应（条件已被改动）→ 丢弃，由最新一次统计收尾
                if (token !== self.previewToken) {
                    return
                }
                let total = 0
                for (let i = 0; i < results.length; i++) {
                    total += results[i].count
                }
                self.previewParts = results
                self.previewCount = total
                self.previewing = false
            }, function (err) {
                if (token !== self.previewToken) {
                    return
                }
                self.previewing = false
                self.previewParts = []
                self.previewCount = null
                if (err && err.isNetwork) {
                    // 真离线（401 由统一请求层处理，不会走到这里）
                    self.offline = true
                    return
                }
                self.previewError = errorText(err)
            })
        },
        /**
         * 统计目标序列：全选 ⇒ `['']`（单次、不限定指标）；部分选 ⇒ 按 `METRIC_TYPES` 固定序逐个。
         * ★ 用 `METRIC_TYPES` 遍历而非 `metricSelection` 原始顺序 ⇒ 结果与开关点击顺序无关（确定性）。
         */
        previewTargets: function () {
            if (this.allMetricsSelected) {
                return ['']
            }
            const targets = []
            for (let i = 0; i < METRIC_TYPES.length; i++) {
                if (this.metricSelection.indexOf(METRIC_TYPES[i]) >= 0) {
                    targets.push(METRIC_TYPES[i])
                }
            }
            return targets
        },

        /* ───────────── 批量删除（R-06，破坏性写） ───────────── */

        onAskDelete: function () {
            // ⑭ 离线不得进入验密流程（按钮已置灰，此处为第二道闸门）
            if (this.deleteDisabled || this.offline) {
                return
            }
            this.pwdValue = ''
            this.pwdError = ''
            this.pwdVisible = true
        },
        onPwdCancel: function () {
            this.pwdVisible = false
            this.pwdValue = ''
            this.pwdError = ''
        },
        onPwdConfirm: function () {
            if (!this.pwdValue) {
                this.pwdError = '请输入登录密码'
                return
            }
            this.pwdVisible = false
            this.confirmText = ''
            this.confirmError = ''
            this.confirmVisible = true
        },
        onConfirmCancel: function () {
            this.confirmVisible = false
            this.confirmText = ''
            this.confirmError = ''
        },
        onConfirmDelete: function () {
            if (this.needConfirmText && this.confirmText.trim() !== CONFIRM_TEXT) {
                this.confirmError = '需填写确认文字「确认删除」'
                return
            }
            this.confirmVisible = false
            this.executeDelete()
        },
        /**
         * 执行删除：按**预览时的同一组合**逐个目标调用 `R-06`，每个请求带自己的 `expected_count`
         * 与**全新的** `Idempotency-Key`（同 key + 不同请求体 → 409，故不能复用）。
         */
        executeDelete: function () {
            const self = this
            const parts = this.previewParts
            const range = this.windowRange
            const password = this.pwdValue
            const withConfirmText = this.needConfirmText
            let deleted = 0

            this.executing = true

            function step(index) {
                if (index >= parts.length) {
                    return Promise.resolve(null)
                }
                const part = parts[index]
                const payload = {}
                if (part.metricType) {
                    payload.metric_type = part.metricType
                }
                if (range.start) {
                    payload.start = range.start
                }
                if (range.end) {
                    payload.end = range.end
                }
                payload.password = password
                payload.expected_count = part.count
                if (withConfirmText) {
                    payload.confirm_text = CONFIRM_TEXT
                }
                return batchDeleteRecords(payload, newIdempotencyKey()).then(function (res) {
                    const raw = res && res.data ? res.data.deleted_count : 0
                    const n = Number(raw)
                    deleted += isNaN(n) || n < 0 ? 0 : n
                    return step(index + 1)
                }, function (err) {
                    return { err: err, index: index }
                })
            }

            return step(0).then(function (failure) {
                self.executing = false
                self.pwdValue = ''

                if (!failure) {
                    showToast('success', '已删除 ' + deleted + ' 条')
                    self.invalidatePreview()
                    self.runPreview()
                    return
                }

                if (deleted > 0) {
                    // ★ 契约缺口 G-10 下的**如实提示**：多目标逐个删除无跨目标事务，
                    //   中途失败确实可能"删了一部分"⇒ 不谎报「数据保持原状」。
                    showToast('error', '已删除 ' + deleted + ' 条，剩余未执行，请刷新后重试')
                    self.invalidatePreview()
                    self.runPreview()
                    return
                }

                const err = failure.err
                if (err && err.code === 'COUNT_MISMATCH') {
                    // ⑫① 不执行删除 + 给出刷新入口：作废旧条数 ⇒ 「预览条数」即刷新入口
                    self.invalidatePreview()
                    self.previewError = '数据已变化，请刷新后重试'
                    return
                }
                if (err && err.code === 'PASSWORD_INVALID') {
                    // ⑫② 密码不正确（回到验密步骤；**已选范围保持不变**，不清空用户的筛选）
                    self.pwdError = '密码不正确'
                    self.pwdVisible = true
                    return
                }
                if (err && err.isNetwork) {
                    self.offline = true
                    showToast('error', errorText(err))
                    return
                }
                showToast('error', '删除失败，请重试')
            })
        },

        /* ───────────── 清空全部数据（D-02，破坏性写） ───────────── */

        onClearAll: function () {
            if (this.clearDisabled) {
                return
            }
            const self = this
            this.clearError = ''
            this.clearing = true

            return clearAllData({
                confirm_text: CONFIRM_TEXT,
                // ★ 声明"已确认不可恢复"：用户已完成红色警示 + 确认文字 + 登录密码三步 ⇒ 布尔 true
                acknowledge_irreversible: true,
                password: this.clearPassword
            }).then(function (res) {
                self.clearing = false
                const data = res && res.data ? res.data : {}
                const raw = Number(data.deleted_records)
                const n = isNaN(raw) || raw < 0 ? 0 : raw
                // ⑯ 成功文案（逐字取自 S1-C SC-22 ⑯，N = 服务端 `deleted_records`）
                showToast('success', '已清除 ' + n + ' 条记录；账号保留，数据已按规则清除')
                self.clearText = ''
                self.clearPassword = ''
                self.clearLocalData()
                self.invalidatePreview()
                self.runPreview()
            }, function (err) {
                self.clearing = false
                if (err && err.isNetwork) {
                    self.offline = true
                    showToast('error', errorText(err))
                    return
                }
                if (err && err.code === 'PASSWORD_INVALID') {
                    self.clearPassword = ''
                    self.clearError = '密码不正确'
                    return
                }
                self.clearError = errorText(err)
            })
        },
        /**
         * 清空本地「业务缓存」与「本地提醒」（⑯「同步清除本地健康数据缓存」+ 后果清单「全部提醒（本地）」）。
         * ★ **登录态必须保留**（D-02 = 保留账号）⇒ 绝不动 `auth.` / `guide.`；
         * ★ 顺序与 `utils/storage.js#clearAuthScopedCache` 一致（I-01）：**先取消系统本地通知，再删本地键**，
         *   否则通知栏会残留已清除的提醒内容。本页只**调用**该能力，未改动任何既有模块。
         */
        clearLocalData: function () {
            try {
                cancelAllRegistered()
            } catch (e) {
                // 通知通道异常不应影响数据清除主流程
            }
            const keys = listKeys()
            for (let i = 0; i < keys.length; i++) {
                const key = keys[i]
                for (let j = 0; j < LOCAL_DATA_PREFIXES.length; j++) {
                    if (key.indexOf(LOCAL_DATA_PREFIXES[j]) === 0) {
                        removeRaw(key)
                        break
                    }
                }
            }
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
            // 恢复只**重刷本页只读预览**（S1-D §5：只刷当前页、**不自动重放写操作**）
            if (this.previewCount !== null || this.previewError) {
                this.runPreview()
            }
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
.dpage {
    min-height: 100vh;
    background-color: var(--s-page);
}

/* A 类系统导航栏的占位由平台负责，此处只留内容区节奏 */
.dpage__body {
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

/* 内容最大宽居中（DESIGN.md §10.4③）+ 唯一水平边距来源 --gutter */
.dpage__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

/* 区块节奏：卡片之间统一走 --card-gap */
.dpage__block {
    margin-bottom: var(--card-gap);
}

/* 说明类小字（指标未选 / 自定义范围提示） */
.dpage__hint {
    display: block;
    margin-top: var(--sp-4);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* 时间范围（C-08）与上方指标行之间拉开节奏 */
.dpage__range {
    margin-top: var(--sp-5);
}

/* 预览行：按钮 + 结果文本。
   文本侧 `flex: 1` **且 `min-width: 0`** ⇒ 长文案在**可收缩**的一侧换行，
   不会把按钮压没（09-17 宽度分配缺陷铁律：不可收缩区不得承载长文本）。 */
.dpage__preview {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-top: var(--sp-5);
}

.dpage__preview-text {
    flex: 1;
    min-width: 0;
    margin-left: var(--sp-4);
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-1);
    text-align: right;
    letter-spacing: 0;
}

/* 失败文案：`--t-danger`（§2.3 登记用途：危险操作文字 / 硬拦截文字） */
.dpage__preview-text--error {
    color: var(--t-danger);
}

/* 主行动按钮与上方内容的间距 */
.dpage__action {
    margin-top: var(--sp-6);
}

/* ── 区块 B：红色警示框（底 = `--c-danger-bg`、边与文字 = `--c-danger`） ── */
.dpage__danger-box {
    background-color: var(--c-danger-bg);
    border: 1rpx solid var(--c-danger);
    border-radius: var(--r-md);
    padding: var(--sp-5);
}

.dpage__danger-title {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-semibold;
    color: var(--t-danger);
    letter-spacing: 0;
}

.dpage__danger-item {
    display: flex;
    flex-direction: row;
    align-items: flex-start;
    margin-top: var(--sp-3);
}

.dpage__danger-mark {
    flex-shrink: 0;
    margin-right: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-danger);
    letter-spacing: 0;
}

.dpage__danger-text {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-2);
    letter-spacing: 0;
}

.dpage__danger-note {
    display: block;
    margin-top: var(--sp-4);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

/* 表单与弹窗正文的节奏 */
.dpage__field {
    margin-top: var(--sp-5);
}

.dpage__modal-text {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-2);
    letter-spacing: 0;
}

/* [② 区分说明行]：纯文字指引（**无跳转按钮**），强调后半句 */
.dpage__distinct-text {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.dpage__distinct-strong {
    font-weight: $fw-semibold;
    color: var(--t-2);
}
</style>
