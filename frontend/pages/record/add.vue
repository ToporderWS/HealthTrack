<template>
    <!--
      SC-08 通用录入页（pages/record/add?type=）  ← 8 类指标共用
      依据：S1-C §二 SC-08 ｜ DESIGN.md §8 / §10.3 / §10.5 / §12 / §13
      顶栏：**A 类系统导航栏**（DESIGN.md §10.3：B 类自绘顶栏不含 SC-08）——
            标题「记录 <指标名>」由 `uni.setNavigationBarTitle` 按 type 动态设置。

      结构（与 S1-C 逐项对应）：
        [① 顶部栏]     系统导航栏（动态标题）
        [② 主数值区]   大号数值输入（首个主字段）+ 单位（固定公制，不可切换）+「上次 <值>」（可点沿用）
        [③ 专属字段区] 按 type 动态渲染（见 utils/recordForm.js 的 EXTRA_FIELDS）
        [④ 时间行]     测量时间（datetime，默认当前时间）；`sleep` 不渲染（其 recorded_at = 起床时间）
        [⑤ 备注]       可选（≤200 字）
        [⑥ 校验条]     软提示（黄，可继续保存）/ 硬拦截（红，阻止保存）—— C-18
        [⑦ 底部按钮]   [保存] [保存并继续记录]（提交中 loading + 禁止重复提交）
        [⑧ 离线提示条]  无网时显示（写入禁用 + 明确提示）

      接口（**只用已封板接口，未改后端**）：
        · `R-08 GET /records/options` 录入字典（单位 / 枚举 / 饮水快捷值）—— 命中本地缓存即无需等待；
        · `R-01 POST /records` 新增保存（**带 `Idempotency-Key`、不自动重试**）；
        · `R-03 GET /records/{id}` 编辑模式预填（S3-3 起）；
        · `R-04 PATCH /records/{id}` 编辑模式保存（S3-3 起；**局部更新、不带 `metric_type`、后端无幂等键**）。

      状态覆盖（DESIGN.md §13）：
        正常 / 加载（本地无字典时骨架屏）/ 失败（字典失败 → 局部失败 + 重试；保存失败 → 明确提示，
        绝不静默）/ 未登录（守卫 → SC-03）/ 离线（**写入禁用** + 离线条 + 内容保留 + 写草稿，**不自动重放**）
        / 提交防重（点击即 loading + disabled；同 key 幂等）/ 软提示（服务端 `SOFT_WARNING`，可继续保存）
        / 硬拦截（本地预检 + 服务端 422，阻止保存，红条）/ 高风险确认（放弃填写）/ 401（统一请求层）
        空态 **N/A**（表单页）｜成功 → Toast「已保存」+ 返回来源页自动刷新。

      ★ 如实登记（本批边界）：
        1. **编辑模式**（`?id=`，入口来自 SC-09 详情页「编辑」）**自 S3-3 起实现**：
           新增模式（无 `id`）逻辑**完全不变**；编辑模式只增加"读 R-03 预填 → 保存走 R-04"这一条支路。
           `metric_type` 在编辑模式下**不允许修改**（本页无该选择器；且 R-04 携带 `metric_type`
           即使值与原值相同也会 422）。
           ★ 编辑模式请求体组装口径（依后端 R-04 语义核对后定案，见 `editPayload()`）：
             后端 `patch_record` 是**真正的局部更新**（`effective = 原值 + 本次改动`，未出现的字段保持原值）；
             且 `metric_rules.validate_record` 的**禁止字段判定基于 `present`（是否显式携带），与值无关**，
             `MATRIX.forbidden` 命中即 422「该指标不支持此字段」。
             ⇒ 编辑模式**只携带"本指标表单实际渲染出的字段"**（这些字段必属允许集合），
               **绝不携带该指标的 forbidden 字段（哪怕传 `null`）**；
               同时对允许字段**总是携带**（允许值为 `null`），否则「清空备注 / 清空标签」无法生效。
             即：payload 字段集 = `MAIN_FIELDS[type]` + `EXTRA_FIELDS[type]`（含 `field` 的项）
               ∪ `{recorded_at, note}` —— 与 S3-2 建立的「后端 MATRIX ↔ 前端渲染字段」交叉断言同源。
        2. **体重 BMI 派生值**不显示：本地无身高来源，且 `P-01` 不在 S1-C SC-08 ⑰ 允许的接口清单内；
           服务端会在保存响应 `derived.bmi` 中返回，展示位置属 SC-09 详情（S3-3）。
        3. 底部按钮为**文档流内布局**（非 fixed）⇒ 任何屏宽下都不可能遮挡内容（§10.4⑥）。
        4. 校验文案口径：数值越界统一用 DESIGN.md §12 固定文案（经 C-18 校验条承载）；
           字段矛盾用**后端冻结的中性技术文案**（如「舒张压不能大于等于收缩压」），不含任何医学判断。
        5. 编辑模式**不参与草稿机制**（不读草稿、不写草稿）—— 避免编辑中途的未提交内容
           污染「新增记录」的草稿槽（草稿按 `metric_type` 切分，两者共用同一槽位）。
    -->
    <view class="add">
        <view class="add__body">
            <view class="add__inner">
                <!-- 参数非法（缺失 / 未知 type）→ 整页错误态 -->
                <view v-if="invalidType" class="add__block">
                    <AppErrorState
                        variant="full"
                        text="指标类型不正确，请从记录中心进入"
                        retry-text="返回记录中心"
                        @retry="backToRecord"
                    />
                </view>

                <template v-else>
                    <!--
                      编辑模式（`?id=`）：记录载入中 / 载入失败。
                      载入完成前**不渲染表单**，避免用户先看到一张空表单、误以为"原来填的数据没了"。
                      新增模式（无 `id`）恒跳过这两个分支，直接进入下方表单区。
                    -->
                    <view v-if="editMode && recordLoading" class="add__block">
                        <AppSkeleton variant="card" />
                    </view>
                    <view v-else-if="editMode && recordErrorText" class="add__block">
                        <AppErrorState
                            variant="full"
                            :text="recordErrorText"
                            :retry-text="recordRetryText"
                            @retry="onRecordRetry"
                        />
                    </view>

                    <!-- 表单区（以下保持原有缩进层级，未整体重排以最小化改动面） -->
                    <template v-else>
                    <!-- ⑧ 离线提示条（无网 → 写入禁用 + 明确提示，S1-C ⑧/⑭②） -->
                    <view v-if="offline" class="add__block">
                        <AppOfflineBar variant="offline" :text="offlineSaveText" />
                    </view>

                    <!-- 离线草稿兜底条（C-31）：仅回填，绝不自动提交 -->
                    <view v-if="draftVisible" class="add__block">
                        <DraftBanner show @continue="onDraftContinue" @restart="onDraftRestart" />
                    </view>

                    <!-- 指标名 + 单位（固定公制，不可切换） -->
                    <view class="add__head">
                        <text class="add__title">{{ title }}</text>
                        <text v-if="unitText" class="add__unit">{{ unitText }}</text>
                    </view>

                    <!-- 字典加载失败（无本地缓存）→ 局部失败 + 重试入口 -->
                    <view v-if="optionsErrorText" class="add__block">
                        <AppErrorState
                            variant="inline"
                            :text="optionsErrorText"
                            retry-text="重试"
                            @retry="loadOptions"
                        />
                    </view>

                    <!-- 字典加载中（仅无缓存时出现，避免整页白屏） -->
                    <view v-if="optionsLoading" class="add__block">
                        <AppSkeleton variant="card" />
                    </view>

                    <!-- ② 主数值区 -->
                    <view
                        v-for="(item, index) in mainFields"
                        :key="item.field"
                        class="add__block"
                    >
                        <view class="add__label-row">
                            <text class="add__label">{{ item.label }}</text>
                            <text v-if="item.required" class="add__required">*</text>
                        </view>

                        <view
                            class="add__value-box"
                            :class="{
                                'add__value-box--big': index === 0,
                                'add__value-box--error': !!visibleErrors[item.field]
                            }"
                        >
                            <input
                                class="add__value-input"
                                :class="{ 'add__value-input--big': index === 0 }"
                                type="digit"
                                :value="form[item.field]"
                                :focus="index === 0 && focusValue"
                                :disabled="submitting"
                                :placeholder="valuePlaceholder"
                                placeholder-style="color: var(--t-4)"
                                @input="onValueInput(item.field, $event)"
                                @blur="onValueBlur(item.field)"
                            />
                            <text v-if="unitText" class="add__value-unit">{{ unitText }}</text>
                        </view>

                        <text v-if="visibleErrors[item.field]" class="add__field-error">
                            {{ visibleErrors[item.field] }}
                        </text>
                        <text
                            v-else-if="index === 0 && lastValueText"
                            class="add__last"
                            hover-class="add__last--press"
                            :hover-start-time="0"
                            :hover-stay-time="80"
                            @tap="useLastValue"
                        >{{ lastValueText }}</text>
                    </view>

                    <!-- ③ 专属字段区（按 type 动态渲染） -->
                    <template v-for="(extra, index) in extraFields" :key="'extra' + index">
                        <!-- 数值字段（如血压的脉搏） -->
                        <view v-if="extra.kind === 'number'" class="add__block">
                            <AppInput
                                :label="extra.label"
                                :unit="extra.unit"
                                :required="extra.required"
                                type="digit"
                                :model-value="form[extra.field]"
                                :disabled="submitting"
                                :error="visibleErrors[extra.field]"
                                @update:model-value="onFieldInput(extra.field, $event)"
                            />
                        </view>

                        <!-- 单选（枚举取值来自 R-08 字典） -->
                        <view v-else-if="extra.kind === 'select'" class="add__block">
                            <AppSelect
                                :label="extra.label"
                                :required="extra.required"
                                :options="enumOptions(extra.enumKey)"
                                :model-value="form[extra.field]"
                                :disabled="submitting || !optionsReady"
                                :error="visibleErrors[extra.field]"
                                @update:model-value="onFieldInput(extra.field, $event)"
                            />
                        </view>

                        <!-- 时间（入睡 / 起床） -->
                        <view v-else-if="extra.kind === 'datetime'" class="add__block">
                            <AppDatePicker
                                :label="extra.label"
                                :required="extra.required"
                                mode="datetime"
                                :model-value="form[extra.field]"
                                :disabled="submitting"
                                :error="visibleErrors[extra.field]"
                                @update:model-value="onFieldInput(extra.field, $event)"
                            />
                        </view>

                        <!-- 饮水快捷添加（步进值来自 R-08 的 water_quick_add） -->
                        <view v-else-if="extra.kind === 'quick'" class="add__block">
                            <text class="add__label">{{ extra.label }}</text>
                            <view class="add__quick">
                                <view
                                    v-for="(amount, quickIndex) in quickAmounts"
                                    :key="'q' + amount"
                                    class="add__quick-btn"
                                    :class="{ 'add__quick-btn--last': quickIndex === quickAmounts.length - 1 }"
                                    hover-class="add__quick-btn--press"
                                    :hover-start-time="0"
                                    :hover-stay-time="80"
                                    @tap="onQuickAdd(amount)"
                                >
                                    <text class="add__quick-text">+{{ amount }} {{ unitText }}</text>
                                </view>
                            </view>
                        </view>

                        <!-- 感受标签（多选，取值来自 R-08 的 mood_tags） -->
                        <view v-else-if="extra.kind === 'tags'" class="add__block">
                            <text class="add__label">{{ extra.label }}</text>
                            <view class="add__tags">
                                <view
                                    v-for="option in enumOptions(extra.enumKey)"
                                    :key="'tag' + option.value"
                                    class="add__tag"
                                    :class="{ 'add__tag--on': isTagOn(option.value) }"
                                    hover-class="add__tag--press"
                                    :hover-start-time="0"
                                    :hover-stay-time="80"
                                    @tap="toggleTag(option.value)"
                                >
                                    <text
                                        class="add__tag-text"
                                        :class="{ 'add__tag-text--on': isTagOn(option.value) }"
                                    >{{ option.label }}</text>
                                </view>
                            </view>
                            <text v-if="visibleErrors.tags" class="add__field-error">{{ visibleErrors.tags }}</text>
                        </view>
                    </template>

                    <!-- 睡眠：入睡 + 起床 → 自动算时长（派生值**只显示数字**，无分级标签） -->
                    <view v-if="sleepDurationText" class="add__block">
                        <text class="add__derived">{{ sleepDurationText }}</text>
                    </view>

                    <!-- ④ 测量时间（sleep 不渲染：其 recorded_at 即起床时间） -->
                    <view v-if="showMeasureTime" class="add__block">
                        <AppDatePicker
                            label="测量时间"
                            mode="datetime"
                            :model-value="form.recorded_at"
                            :disabled="submitting"
                            :error="visibleErrors.recorded_at"
                            @update:model-value="onFieldInput('recorded_at', $event)"
                        />
                    </view>

                    <!-- ⑤ 备注（可选） -->
                    <view class="add__block">
                        <AppInput
                            label="备注"
                            placeholder="可不填"
                            :maxlength="noteMax"
                            :model-value="form.note"
                            :disabled="submitting"
                            :error="visibleErrors.note"
                            @update:model-value="onFieldInput('note', $event)"
                        />
                    </view>

                    <!-- ⑥ 校验条：软提示（黄，可继续保存）/ 硬拦截（红，阻止保存） -->
                    <view v-if="softVisible" class="add__block">
                        <AppValidateBar visible level="soft" />
                    </view>
                    <view v-if="blockVisible" class="add__block">
                        <AppValidateBar visible level="block" />
                    </view>

                    <!-- ⑦ 底部按钮
                         编辑模式只保留 [保存]：[保存并继续记录] 的语义是"连续新增多条"，
                         与"修改同一条记录"互斥（S1-C ⑦：编辑模式保存后回详情页）。 -->
                    <view class="add__foot">
                        <view class="add__foot-item">
                            <AppButton
                                label="保存"
                                block
                                :loading="submitting"
                                :disabled="saveDisabled"
                                @tap="onSave"
                            />
                        </view>
                        <view v-if="!editMode" class="add__foot-item">
                            <AppButton
                                label="保存并继续记录"
                                type="secondary"
                                block
                                :disabled="saveDisabled"
                                @tap="onSaveContinue"
                            />
                        </view>
                    </view>
                    </template>
                </template>
            </view>
        </view>

        <!-- 放弃二次确认（S1-C §三 第 10 条：标题 + 说明 + [继续填写][放弃]）
             遮罩不可关闭：避免误触丢弃已修改 / 已填内容；
             文案随模式适配（新增 = "放弃填写"，编辑 = "放弃修改"） -->
        <AppModal
            :show="leaveVisible"
            :title="leaveTitle"
            :content="leaveContent"
            confirm-text="继续填写"
            cancel-text="放弃"
            :close-on-mask="false"
            @confirm="onKeepEditing"
            @cancel="onDiscard"
        />

        <!-- 轻提示宿主（成功 / 失败 / 会话失效提示经此渲染） -->
        <AppToast />
    </view>
</template>

<script>
import AppButton from '../../components/AppButton.vue'
import AppInput from '../../components/AppInput.vue'
import AppSelect from '../../components/AppSelect.vue'
import AppDatePicker from '../../components/AppDatePicker.vue'
import AppValidateBar from '../../components/AppValidateBar.vue'
import AppModal from '../../components/AppModal.vue'
import AppToast from '../../components/AppToast.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import DraftBanner from '../../components/DraftBanner.vue'

import { ROUTES, navigateBack, reLaunch, requireLogin } from '../../utils/route'
import { metricLabel, metricUnit, toMinute } from '../../utils/metrics'
import { CACHE_KEYS, loadCache, saveCache, formatStamp } from '../../utils/cache'
import { isOnline, offlineText } from '../../utils/network'
import { showToast } from '../../utils/toast'
import { newIdempotencyKey, errorText, fieldErrorText } from '../../utils/request'
import { RANGE_TEXT } from '../../utils/validate'
import { fetchRecordOptions, createRecord, getRecord, updateRecord } from '../../api/records'
import { loadDraft, saveDraft, dropDraft } from '../../utils/draft'
import {
    FORM_TYPES, MAIN_FIELDS, EXTRA_FIELDS, MEASURE_TIME_TYPES,
    NOTE_MAX, MOOD_TAG_MAX, HARD_RANGE, DOMAIN_RANGE,
    SLEEP_DURATION_HARD_HOURS, withinRange, parseNumber, decimalsOf, decimalsExceeded,
    parseStamp, sleepDurationHours
} from '../../utils/recordForm'

/** 数值超出常见范围（DESIGN.md §12 固定文案，**单一来源 = utils/validate.js**） */

/** 未填写（中性技术文案） */
const REQUIRED_TEXT = '请填写'
/** 未选择（中性技术文案） */
const SELECT_TEXT = '请选择'
/** 非数字（中性技术文案） */
const NUMBER_TEXT = '请输入数字'
/** 小数位超限（中性技术文案） */
const DECIMAL_TEXT = '数值格式不正确'
/** 字段矛盾（与后端冻结文案一致，不含任何医学判断） */
const BP_ORDER_TEXT = '舒张压不能大于等于收缩压'
const SLEEP_ORDER_TEXT = '入睡时间须早于起床时间'
/** 时间格式（中性技术文案） */
const TIME_TEXT = '时间格式不正确'
/** 未来时间（与后端冻结文案一致） */
const FUTURE_TEXT = '记录时间不得晚于当前时间'

/* ── 编辑模式（`?id=`，S3-3）专用文案 ── */

/** 编辑模式：预填失败（中性技术文案） */
const EDIT_LOAD_FAIL_TEXT = '加载失败，请稍后重试'
/** 编辑模式：记录不存在（不存在 / 非本人 / 已软删 —— 后端统一 404，**统一按"记录不存在"提示**） */
const EDIT_NOT_FOUND_TEXT = '记录不存在'
/** 编辑模式：离线无法拉取待编辑的记录（绝不假装能编辑） */
const EDIT_OFFLINE_TEXT = '当前离线，无法加载要编辑的记录'
/** 编辑模式：记录的指标类型不在支持范围内（理论上不可达，作兜底） */
const EDIT_UNSUPPORTED_TEXT = '该记录的指标类型暂不支持编辑'
/** 编辑模式保存成功文案（与新增模式同口径的"已保存"） */
const EDITED_TOAST_TEXT = '已保存'

/** 数值 / 字符串 → 表单文本（`null` / `undefined` / `''` → `''`，**不产生 "null" 字面量**） */
function numberText(value) {
    if (value === null || value === undefined || value === '') {
        return ''
    }
    return String(value)
}

export default {
    components: {
        AppButton: AppButton,
        AppInput: AppInput,
        AppSelect: AppSelect,
        AppDatePicker: AppDatePicker,
        AppValidateBar: AppValidateBar,
        AppModal: AppModal,
        AppToast: AppToast,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState,
        AppOfflineBar: AppOfflineBar,
        DraftBanner: DraftBanner
    },
    data: function () {
        return {
            /** 指标类型（来自 `?type=`；编辑模式下可由 R-03 返回的 `metric_type` 补齐） */
            metricType: '',
            /** 参数非法（缺失 / 未知 type，且非编辑模式）→ 整页错误态 */
            invalidType: false,

            /* ── 编辑模式（`?id=`，S3-3）── */
            /** 是否编辑模式（存在 `?id=`） */
            editMode: false,
            /** 待编辑记录 id */
            recordId: '',
            /** 记录载入中（载入完成前**不渲染表单**） */
            recordLoading: false,
            /** 记录载入失败文案（非空 → 整页失败态 / 不存在态） */
            recordErrorText: '',
            /** 记录不存在（不存在 / 非本人 / 已软删；决定失败态按钮的去向） */
            recordNotFound: false,
            /** 预填完成后的表单快照（用于"是否已修改"判定 —— 未改动就返回不弹放弃确认） */
            loadedSnapshot: null,

            /** `R-08` 字典（`{ metric_types, enums, water_quick_add }`） */
            options: null,
            optionsReady: false,
            optionsLoading: false,
            optionsErrorText: '',

            /** 离线（网络不可用 → **写入禁用** + 明确提示） */
            offline: false,

            /** 提交中（点击即 loading + 禁用，防重复提交） */
            submitting: false,
            /** 已成功保存并已离开（避免返回时误写草稿） */
            savedOnce: false,
            /** 幂等键（首次提交时生成；软提示确认重发**沿用同一 key**） */
            submitKey: null,
            /** 服务端已返回软提示 → 下一次提交携带 `acknowledge_warnings: true` */
            serverSoft: false,

            /** 校验结果 */
            blockText: '',
            fieldErrors: {},
            /** 已交互过的字段（用于「不打扰」：未交互前不显示必填红字，但保存仍禁用） */
            touched: {},
            /** 是否已尝试提交过（提交后一次性暴露所有字段错误） */
            attempted: false,

            /** 主数值输入聚焦标记（「保存并继续记录」后焦点回到输入框） */
            focusValue: false,

            /** 当前键盘高度（DESIGN.md §10.5 监听；本页底栏为文档流布局，暂不参与定位） */
            keyboardHeight: 0,

            /** 表单（字段名与后端契约逐字一致；**不提交 unit**，由服务端按指标填充） */
            form: {
                value_1: '',
                value_2: '',
                value_3: '',
                attr_1: '',
                attr_2: '',
                time_start: '',
                recorded_at: '',
                note: '',
                tags: []
            },

            /** 草稿 */
            draftAvailable: false,
            draftVisible: false,
            draftForm: null,
            draftSavedAt: '',

            /** 「上次值」（来源：S-01 本地缓存，**不新增接口调用**） */
            lastRecord: null,

            /** 放弃填写确认 */
            leaveVisible: false,

            /** 内部句柄 */
            networkHandler: null,
            keyboardHandler: null
        }
    },
    computed: {
        labelText: function () {
            return metricLabel(this.metricType)
        },
        title: function () {
            if (!this.metricType) {
                return this.editMode ? '编辑记录' : '记录'
            }
            return (this.editMode ? '编辑 ' : '记录 ') + this.labelText
        },
        /** 放弃确认弹窗标题（随模式适配：新增＝放弃填写 / 编辑＝放弃修改） */
        leaveTitle: function () {
            return this.editMode ? '放弃修改' : '放弃填写'
        },
        /** 放弃确认弹窗说明（随模式适配） */
        leaveContent: function () {
            return this.editMode ? '已修改内容，确定放弃？' : '已有输入内容，确定放弃？'
        },
        /** 编辑模式失败态的按钮文案（记录不存在 → 回记录中心；其他 → 重试） */
        recordRetryText: function () {
            return this.recordNotFound ? '返回记录中心' : '重试'
        },
        /** 单位：优先用 `R-08` 下发值，缺省回退到冻结字典（客户端不自行发明） */
        unitText: function () {
            if (!this.metricType) {
                return ''
            }
            return metricUnit(this.metricType, this.metricUnitFromApi(this.metricType))
        },
        mainFields: function () {
            return MAIN_FIELDS[this.metricType] || []
        },
        extraFields: function () {
            return EXTRA_FIELDS[this.metricType] || []
        },
        showMeasureTime: function () {
            return MEASURE_TIME_TYPES.indexOf(this.metricType) >= 0
        },
        quickAmounts: function () {
            const list = this.options && this.options.water_quick_add
            return list && list.length ? list : []
        },
        noteMax: function () {
            return NOTE_MAX
        },
        /** 主数值输入占位（**不含任何参考区间 / 医学值**） */
        valuePlaceholder: function () {
            return '请输入'
        },
        /** 离线条文案（S1-C ⑭② 固定文案） */
        offlineSaveText: function () {
            return offlineText('save')
        },
        /** 软提示条：仅服务端判定 `SOFT_WARNING` 时出现（可继续保存） */
        softVisible: function () {
            return this.serverSoft && !this.blockText
        },
        /** 硬拦截条：本地预检命中不可能值 / 定义域越界时出现（阻止保存） */
        blockVisible: function () {
            return !!this.blockText
        },
        /** 「上次 <值>」提示（有历史值且当前主字段为空时展示，可点击沿用） */
        lastValueText: function () {
            const record = this.lastRecord
            if (!record) {
                return ''
            }
            const value = record.value_1
            if (value === null || value === undefined || value === '') {
                return ''
            }
            const unit = this.unitText
            const time = toMinute(record.recorded_at)
            const head = unit ? String(value) + ' ' + unit : String(value)
            return time ? '上次 ' + head + ' · ' + time : '上次 ' + head
        },
        /** 睡眠时长（派生值，**只显示数字**；非法 / 缺失 → 不渲染） */
        sleepDurationText: function () {
            if (this.metricType !== 'sleep') {
                return ''
            }
            const hours = sleepDurationHours(this.form.time_start, this.form.recorded_at)
            if (hours === null) {
                return ''
            }
            return '睡眠时长 ' + hours + ' 小时'
        },
        /** 保存按钮是否禁用（提交中 / 参数非法 / 离线 / 编辑未就绪 / 硬拦截 / 必填缺失） */
        saveDisabled: function () {
            if (this.submitting || this.offline || this.invalidType) {
                return true
            }
            // 编辑模式：记录尚未载入完成 / 载入失败 → 不可保存（绝不把空表单当"清空全部"提交）
            if (this.editMode && (this.recordLoading || !!this.recordErrorText)) {
                return true
            }
            if (this.blockText) {
                return true
            }
            return this.hasFieldError()
        },
        /**
         * 对外**展示**的字段错误（DESIGN.md §13 底线清单 ⑫ 的"不打扰"实现）：
         * `fieldErrors` 始终参与按钮禁用判定，但只有**已交互过的字段**或**已尝试提交**后才显示，
         * 避免用户一进页面就看到「请填写」红字。服务端 422 回填的错误同样受此规则约束
         * （提交必然先置 `attempted=true`，故不会被吞掉）。
         */
        visibleErrors: function () {
            const out = {}
            const src = this.fieldErrors
            const all = this.attempted
            for (const key in src) {
                if (!Object.prototype.hasOwnProperty.call(src, key) || !src[key]) {
                    continue
                }
                if (all || this.touched[key]) {
                    out[key] = src[key]
                }
            }
            return out
        }
    },
    onLoad: function (query) {
        // 未登录守卫（S1-C SC-08 ⑬：需登录；已填内容写入草稿后跳转）
        if (!requireLogin()) {
            return
        }

        // 编辑模式（S3-3）：存在 `?id=` 即进入编辑；此时 `?type=` 仅作初始兜底
        const id = query && query.id !== undefined && query.id !== null ? String(query.id) : ''
        this.editMode = !!id
        this.recordId = id

        const type = query && query.type ? String(query.type) : ''
        if (FORM_TYPES.indexOf(type) < 0 && !this.editMode) {
            // 新增模式：`?type=` 必须合法（编辑模式可由 R-03 返回的 `metric_type` 补齐）
            this.invalidType = true
            return
        }
        if (FORM_TYPES.indexOf(type) >= 0) {
            this.metricType = type
        }

        // 导航栏标题：「记录 / 编辑 <指标名>」（A 类系统导航栏，标题按 type 动态设置）
        uni.setNavigationBarTitle({ title: this.title })

        // 网络状态（离线 → 写入禁用 + 明确提示；恢复 → 解除禁用，**不自动重放**）
        const self = this
        this.networkHandler = function (res) {
            self.offline = !(res && res.isConnected)
        }
        uni.onNetworkStatusChange(this.networkHandler)
        isOnline().then(function (online) {
            self.offline = !online
        })

        // 键盘高度监听（DESIGN.md §10.5：表单页监听键盘高度变化）。
        // 本页底部按钮为**文档流内布局**（非 fixed）⇒ 键盘弹出不会遮挡按钮；
        // 此处保留监听以符合 §10.5，并在未来改为固定底栏时可直接复用该回调。
        // ★ 能力守卫：`onKeyboardHeightChange` 在各端支持不一致（H5 端可能不存在），
        //   直接调用会抛 TypeError 导致本页白屏 —— 故先做存在性判断，缺失时静默降级。
        this.keyboardHandler = function (res) {
            const height = res && res.height ? Number(res.height) : 0
            self.keyboardHeight = isNaN(height) ? 0 : height
        }
        if (typeof uni.onKeyboardHeightChange === 'function') {
            uni.onKeyboardHeightChange(this.keyboardHandler)
        } else {
            this.keyboardHandler = null
        }

        // 字典：先读缓存（离线可填写），再向服务端刷新
        // （**两种模式都需要**：`select` 的枚举选项与单位展示都依赖 R-08）
        this.loadOptions()

        if (this.editMode) {
            /*
             * 编辑模式：只拉取该条记录并预填。刻意**不做**三件事（如实登记）：
             *   ① 不把 `recorded_at` 重置为当前时间 —— 编辑要保留原记录的测量时间；
             *   ② 不读「上次值」—— 编辑不是"再记一条"，沿用上次值会产生误导；
             *   ③ 不读 / 不写草稿 —— 避免编辑中途内容污染新增模式的草稿槽（草稿按指标切分）。
             */
            this.loadRecord()
            return
        }

        // ── 以下为新增模式（逻辑与 S3-2 完全一致，未做任何改动）──

        // 时间基准 = 当前时间（S1-C ④；服务端会校验 `recorded_at` 不得晚于当前时间）
        this.form.recorded_at = formatStamp(new Date())

        // 「上次值」与草稿：**只读本地**，不发请求
        this.readLastRecord()
        this.restoreDraft()

        this.revalidate()
    },
    onHide: function () {
        // 离开页面：保留已填内容（写草稿），下次进入提示「有未提交内容，是否继续？」
        this.persistDraft()
    },
    onUnload: function () {
        this.persistDraft()
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
        if (this.keyboardHandler && typeof uni.offKeyboardHeightChange === 'function') {
            uni.offKeyboardHeightChange(this.keyboardHandler)
        }
        this.keyboardHandler = null
    },
    /**
     * 返回拦截：已有输入 → 二次确认「已有输入内容，确定放弃？」（S1-C ⑮①）。
     *
     * ★ 必须放行 `from === 'navigateBack'`（uni-app 官方约定）：
     *   `uni.navigateBack()` 自身也会触发本钩子，且其 `from` 为 `'navigateBack'`
     *   （`from` = `'backbutton'` 表示左上角返回按钮 / Android 实体返回键）。
     *   若在此情形下仍返回 `true`，运行时会**中止这次返回**并以
     *   `navigateBack:fail onBackPress` 拒绝该 Promise ⇒ 表现为：
     *   ① 「放弃」「保存成功自动返回」失效；② 控制台出现未捕获错误；
     *   ③ 因 `hasContent()` 仍为真而把弹窗重新打开，形成无法返回的环路。
     *   官方推荐写法即：来源为 `navigateBack` 时返回 `false` 放行，只拦截物理/导航栏返回。
     *
     * 平台差异**如实登记**：H5 的浏览器返回键不经过本钩子（官方文档明确），
     * 因此 `onHide` / `onUnload` 的草稿兜底是本页「不丢内容」的最终保障。
     */
    onBackPress: function (options) {
        if (options && options.from === 'navigateBack') {
            return false
        }
        if (this.submitting || !this.hasContent()) {
            return false
        }
        this.leaveVisible = true
        return true
    },
    methods: {
        /* ───────────── 数据：字典 / 本地缓存 ───────────── */

        metricUnitFromApi: function (type) {
            const list = this.options && this.options.metric_types
            if (list && list.length) {
                for (let i = 0; i < list.length; i++) {
                    if (list[i].value === type) {
                        return list[i].unit
                    }
                }
            }
            return ''
        },

        enumOptions: function (enumKey) {
            const enums = this.options && this.options.enums
            if (!enums || !enumKey) {
                return []
            }
            const list = enums[enumKey]
            return list && list.length ? list : []
        },

        /** R-08 字典：命中缓存先用（离线可填写的依据），随后静默刷新并回写缓存 */
        loadOptions: function () {
            const self = this
            const cached = loadCache(CACHE_KEYS.RECORD_OPTIONS)
            if (cached && cached.data) {
                this.options = cached.data
                this.optionsReady = true
                this.optionsLoading = false
                this.optionsErrorText = ''
                this.revalidate()
            } else {
                this.optionsLoading = true
                this.optionsErrorText = ''
            }

            return fetchRecordOptions().then(function (res) {
                const data = res && res.data ? res.data : null
                self.optionsLoading = false
                if (!data) {
                    if (!self.optionsReady) {
                        self.optionsErrorText = '加载失败，点击重试'
                    }
                    return
                }
                self.options = data
                self.optionsReady = true
                self.optionsErrorText = ''
                saveCache(CACHE_KEYS.RECORD_OPTIONS, data)
                self.revalidate()
            }, function (err) {
                self.optionsLoading = false
                if (!self.optionsReady) {
                    // 局部失败：只有「字典相关」字段受影响，数值输入仍可用，并给出重试入口
                    self.optionsErrorText = errorText(err)
                }
            })
        },

        /** 「上次值」（S-01 本地缓存；**零新增请求**；无缓存则整行不渲染） */
        readLastRecord: function () {
            const cached = loadCache(CACHE_KEYS.HOME_OVERVIEW)
            const list = cached && cached.data ? cached.data.recent_records : null
            this.lastRecord = null
            if (!list || !list.length) {
                return
            }
            for (let i = 0; i < list.length; i++) {
                if (list[i] && list[i].metric_type === this.metricType) {
                    this.lastRecord = list[i]
                    return
                }
            }
        },

        /* ───────────── 草稿 ───────────── */

        restoreDraft: function () {
            const draft = loadDraft(this.metricType)
            if (!draft) {
                this.draftAvailable = false
                this.draftVisible = false
                return
            }
            this.draftAvailable = true
            this.draftForm = draft.form
            this.draftSavedAt = draft.savedAt
            // **仅提示，不回填、绝不自动提交**（S1-C ⑭④）
            this.draftVisible = true
        },

        /** 「继续填写」→ 回填草稿（仅回填） */
        onDraftContinue: function () {
            const saved = this.draftForm || {}
            const form = this.form
            const keys = ['value_1', 'value_2', 'value_3', 'attr_1', 'attr_2', 'time_start', 'recorded_at', 'note']
            keys.forEach(function (key) {
                if (saved[key] !== undefined && saved[key] !== null) {
                    form[key] = saved[key]
                }
            })
            if (saved.tags && saved.tags.length) {
                form.tags = saved.tags.slice(0, MOOD_TAG_MAX)
            }
            // 草稿回填视同"已交互"：回填后立即校验并展示相应提示
            this.touched = {
                value_1: true, value_2: true, value_3: true,
                attr_1: true, attr_2: true, time_start: true, recorded_at: true,
                note: true, tags: true
            }
            this.draftVisible = false
            this.revalidate()
        },

        /** 「重新开始」→ 丢弃草稿并清空数值/标签/备注 */
        onDraftRestart: function () {
            dropDraft(this.metricType)
            this.draftAvailable = false
            this.draftForm = null
            this.draftSavedAt = ''
            this.draftVisible = false
            this.form.value_1 = ''
            this.form.value_2 = ''
            this.form.value_3 = ''
            this.form.tags = []
            this.form.note = ''
            this.touched = {}
            this.attempted = false
            this.serverSoft = false
            this.revalidate()
        },

        /** 写草稿（仅当确有内容，且不是刚保存成功离开） */
        persistDraft: function () {
            // ★ 编辑模式不写草稿：草稿槽按 `metric_type` 切分，与新增模式共用同一槽位，
            //   若在此写入，用户下次"新增记录"时会被提示恢复一条"其实是在改的旧记录"。
            if (this.editMode) {
                return
            }
            if (!this.metricType || this.invalidType || this.savedOnce || !this.hasContent()) {
                return
            }
            saveDraft(this.metricType, this.snapshotForm())
        },

        snapshotForm: function () {
            const form = this.form
            return {
                value_1: form.value_1,
                value_2: form.value_2,
                value_3: form.value_3,
                attr_1: form.attr_1,
                attr_2: form.attr_2,
                time_start: form.time_start,
                recorded_at: form.recorded_at,
                note: form.note,
                /* 深拷贝：快照必须与后续对 `form.tags` 的**整数组替换**解耦
                   （编辑模式的"是否已修改"判定依赖它保持初始值） */
                tags: (form.tags || []).slice()
            }
        },

        /** 是否存在用户已输入内容（用于返回确认与草稿判定） */
        hasContent: function () {
            // 编辑模式：「有内容」的判断基准是**是否真的改过** ——
            // 未做任何改动就返回时不应弹"放弃修改"（那会是无意义打扰）。
            if (this.editMode) {
                return this.isEdited()
            }
            const form = this.form
            const filled = ['value_1', 'value_2', 'value_3', 'attr_1', 'attr_2', 'note']
            for (let i = 0; i < filled.length; i++) {
                const value = form[filled[i]]
                if (value !== null && value !== undefined && String(value).trim() !== '') {
                    return true
                }
            }
            if (form.tags && form.tags.length) {
                return true
            }
            // `sleep` 的入睡时间属用户输入；`recorded_at` 是默认时间基准，不计入
            return !!(form.time_start && String(form.time_start).trim())
        },

        /* ───────────── 表单交互 ───────────── */

        onValueInput: function (field, event) {
            const value = event && event.detail ? event.detail.value : ''
            this.form[field] = value
            this.touched[field] = true
            this.serverSoft = false
            this.revalidate()
        },

        /** 失焦：把该字段标记为"已交互"，此后才展示其校验提示（避免一进页面就满屏红字） */
        onValueBlur: function (field) {
            if (field) {
                this.touched[field] = true
            }
            this.focusValue = false
        },

        onFieldInput: function (field, value) {
            this.form[field] = value === undefined || value === null ? '' : value
            this.touched[field] = true
            this.serverSoft = false
            this.revalidate()
        },

        /** 饮水快捷添加（在已填值上累加，未填视为 0） */
        onQuickAdd: function (amount) {
            const current = parseNumber(this.form.value_1)
            const next = (current === null ? 0 : current) + Number(amount)
            this.form.value_1 = String(next)
            this.touched.value_1 = true
            this.serverSoft = false
            this.revalidate()
        },

        isTagOn: function (value) {
            return (this.form.tags || []).indexOf(value) >= 0
        },

        toggleTag: function (value) {
            const tags = (this.form.tags || []).slice()
            const index = tags.indexOf(value)
            if (index >= 0) {
                tags.splice(index, 1)
            } else {
                if (tags.length >= MOOD_TAG_MAX) {
                    // 上限来自后端 `validate_tags`（> 6 → 422）—— 中性技术提示
                    showToast('info', '标签最多选择 ' + MOOD_TAG_MAX + ' 个')
                    return
                }
                tags.push(value)
            }
            this.form.tags = tags
            this.touched.tags = true
            this.revalidate()
        },

        /** 沿用上次值（点击「上次 <值>」） */
        useLastValue: function () {
            const record = this.lastRecord
            if (!record || record.value_1 === null || record.value_1 === undefined) {
                return
            }
            this.form.value_1 = String(record.value_1)
            this.touched.value_1 = true
            this.serverSoft = false
            this.revalidate()
        },

        /* ───────────── 校验（只识别录入错误，不做任何医学判断） ───────────── */

        /**
         * 本地预检：
         *   - 硬拦截级（必填 / 非数字 / 精度 / 定义域 / 不可能值 / 字段矛盾 / 未来时间 / 备注超长）；
         *   - **软提示（"超出常见范围但仍可能真实存在"）由服务端 `SOFT_WARNING` 裁决**，
         *     客户端不重复判定，避免两套口径漂移。
         */
        revalidate: function () {
            const errors = {}
            let block = ''

            if (!this.metricType) {
                this.fieldErrors = errors
                this.blockText = block
                return
            }

            const numeric = ['value_1', 'value_2', 'value_3']
            for (let i = 0; i < numeric.length; i++) {
                const field = numeric[i]
                const raw = this.form[field]
                const text = raw === null || raw === undefined ? '' : String(raw).trim()

                if (!text) {
                    if (this.isRequired(field)) {
                        errors[field] = REQUIRED_TEXT
                    }
                    continue
                }
                const num = parseNumber(text)
                if (num === null) {
                    errors[field] = NUMBER_TEXT
                    continue
                }
                const allowed = decimalsOf(this.metricType, field)
                if (allowed !== null && decimalsExceeded(text, allowed)) {
                    errors[field] = DECIMAL_TEXT
                    continue
                }
                const domain = (DOMAIN_RANGE[this.metricType] || {})[field]
                if (domain && !withinRange(num, domain)) {
                    block = RANGE_TEXT
                }
                const hard = (HARD_RANGE[this.metricType] || {})[field]
                if (hard && !withinRange(num, hard)) {
                    block = RANGE_TEXT
                }
            }

            // 字段矛盾（与后端同口径）
            if (this.metricType === 'bp') {
                const high = parseNumber(this.form.value_1)
                const low = parseNumber(this.form.value_2)
                if (high !== null && low !== null && low >= high) {
                    errors.value_2 = BP_ORDER_TEXT
                }
            }
            if (this.metricType === 'sleep') {
                const start = this.form.time_start
                const end = this.form.recorded_at
                if (start && end) {
                    const from = parseStamp(start)
                    const to = parseStamp(end)
                    if (from === null) {
                        errors.time_start = TIME_TEXT
                    } else if (to === null) {
                        errors.recorded_at = TIME_TEXT
                    } else if (from >= to) {
                        errors.time_start = SLEEP_ORDER_TEXT
                    } else {
                        const hours = (to - from) / 3600000
                        if (!withinRange(hours, SLEEP_DURATION_HARD_HOURS)) {
                            block = RANGE_TEXT
                        }
                    }
                }
            }

            // 必选枚举（选项来自 R-08）
            const extras = this.extraFields
            for (let i = 0; i < extras.length; i++) {
                const extra = extras[i]
                if (extra.kind !== 'select' || !extra.required) {
                    continue
                }
                if (!this.form[extra.field]) {
                    errors[extra.field] = SELECT_TEXT
                }
            }

            // 时间：不得为未来（与后端 `_future_guard` 同口径）
            if (this.form.recorded_at) {
                const stamp = parseStamp(this.form.recorded_at)
                if (stamp === null) {
                    errors.recorded_at = TIME_TEXT
                } else if (stamp > Date.now()) {
                    errors.recorded_at = FUTURE_TEXT
                }
            }

            // 备注长度（后端 > 200 → 422）
            if (this.form.note && String(this.form.note).length > NOTE_MAX) {
                errors.note = '备注不超过 ' + NOTE_MAX + ' 字'
            }

            this.fieldErrors = errors
            this.blockText = block
        },

        /** 该字段是否必填（取自字段矩阵的 `required` 标记） */
        isRequired: function (field) {
            const mains = this.mainFields
            for (let i = 0; i < mains.length; i++) {
                if (mains[i].field === field) {
                    return !!mains[i].required
                }
            }
            const extras = this.extraFields
            for (let i = 0; i < extras.length; i++) {
                if (extras[i].field === field) {
                    return !!extras[i].required
                }
            }
            return false
        },

        hasFieldError: function () {
            const map = this.fieldErrors
            for (const key in map) {
                if (Object.prototype.hasOwnProperty.call(map, key) && map[key]) {
                    return true
                }
            }
            return false
        },

        /* ───────────── 编辑模式（R-03 / R-04，S3-3） ───────────── */

        /**
         * 拉取待编辑的记录并预填表单（R-03）。
         *
         * 失败分支（与 SC-09 详情页同口径）：
         *   ① 网络失败 → `offline = true` + 明确提示（**离线不假装能编辑**）；
         *   ② 404 → **统一按「记录不存在」**（不存在 / 非本人 / 已软删，后端不区分）；
         *   ③ 其他 → 中性失败文案 + 重试。
         */
        loadRecord: function () {
            const self = this
            this.recordLoading = true
            this.recordErrorText = ''
            this.recordNotFound = false
            return getRecord(this.recordId).then(function (res) {
                self.recordLoading = false
                const data = res && res.data ? res.data : null
                if (!data || !data.record) {
                    self.recordErrorText = EDIT_LOAD_FAIL_TEXT
                    return
                }
                self.applyRecord(data.record)
            }, function (err) {
                self.recordLoading = false
                if (err && err.isNetwork) {
                    self.offline = true
                    self.recordErrorText = EDIT_OFFLINE_TEXT
                    return
                }
                if (err && (err.httpStatus === 404 || err.code === 'RESOURCE_NOT_FOUND')) {
                    self.recordNotFound = true
                    self.recordErrorText = EDIT_NOT_FOUND_TEXT
                    return
                }
                self.recordErrorText = errorText(err)
            })
        },

        /**
         * 把 R-03 返回的记录预填进表单。
         * `metric_type` **只读**：取值来自记录本身（`?type=` 仅作兜底），页面上没有修改入口。
         */
        applyRecord: function (record) {
            const type = record && record.metric_type ? String(record.metric_type) : ''
            if (FORM_TYPES.indexOf(type) < 0) {
                // 兜底：类型不在客户端支持范围（理论上不可达 —— 表单只会产出这 8 类）
                this.recordErrorText = EDIT_UNSUPPORTED_TEXT
                return
            }
            this.metricType = type
            // 类型确定后补正导航栏标题（`?type=` 缺失时 onLoad 阶段还拿不到指标名）
            uni.setNavigationBarTitle({ title: this.title })

            const form = this.form
            form.value_1 = numberText(record.value_1)
            form.value_2 = numberText(record.value_2)
            form.value_3 = numberText(record.value_3)
            form.attr_1 = record.attr_1 ? String(record.attr_1) : ''
            form.attr_2 = record.attr_2 ? String(record.attr_2) : ''
            form.time_start = record.time_start ? String(record.time_start) : ''
            form.recorded_at = record.recorded_at ? String(record.recorded_at) : ''
            form.note = record.note ? String(record.note) : ''
            form.tags = record.tags && record.tags.length ? record.tags.slice(0, MOOD_TAG_MAX) : []

            // 预填完成 → 记下基线快照（此后"有没有改过"以它为基准，见 `isEdited`）
            this.loadedSnapshot = this.snapshotForm()
            // 预填**不算**用户交互：清空 `touched`，避免一进页面就满屏红字
            this.touched = {}
            this.attempted = false
            this.serverSoft = false
            this.revalidate()
        },

        /** 编辑模式失败态的重试（「记录不存在」→ 回记录中心；其他 → 重新拉取） */
        onRecordRetry: function () {
            if (this.recordNotFound) {
                this.backToRecord()
                return
            }
            this.loadRecord()
        },

        /**
         * 编辑模式：当前表单相对**预填基线**是否已有改动。
         * 用途：返回拦截（未改动 → 不弹"放弃修改"，不做无意义打扰）。
         * 说明：`tags` 按集合比较（顺序变化不算改动）。
         */
        isEdited: function () {
            const base = this.loadedSnapshot
            if (!base) {
                return false
            }
            const now = this.snapshotForm()
            const keys = ['value_1', 'value_2', 'value_3', 'attr_1', 'attr_2', 'time_start', 'recorded_at', 'note']
            for (let i = 0; i < keys.length; i++) {
                const key = keys[i]
                const a = now[key] === null || now[key] === undefined ? '' : String(now[key])
                const b = base[key] === null || base[key] === undefined ? '' : String(base[key])
                if (a !== b) {
                    return true
                }
            }
            const left = (now.tags || []).slice().sort().join('|')
            const right = (base.tags || []).slice().sort().join('|')
            return left !== right
        },

        /**
         * 编辑模式请求体的**字段白名单** = 本指标表单实际渲染出的字段 ∪ `{recorded_at, note}`。
         *
         * 依据（后端契约核对结论，勿改）：
         *   · `MAIN_FIELDS` / `EXTRA_FIELDS` 渲染出的字段**必属后端允许集合**
         *     （S3-2 已建立「后端 MATRIX ↔ 前端渲染字段」双向交叉断言）；
         *   · `note` 与 `recorded_at` 不在任何指标的 `MATRIX.forbidden` 中 ⇒ 恒可携带；
         *   · 其余字段（如体重的 `value_2`、心情的 `time_start`）**必须不出现** ——
         *     后端「禁止字段」判定看的是 `present`（是否显式携带），**与值是否为 `null` 无关**。
         */
        allowedFields: function () {
            const out = ['recorded_at', 'note']
            const mains = this.mainFields
            for (let i = 0; i < mains.length; i++) {
                out.push(mains[i].field)
            }
            const extras = this.extraFields
            for (let i = 0; i < extras.length; i++) {
                if (extras[i].field) {
                    out.push(extras[i].field)
                }
            }
            const unique = []
            for (let i = 0; i < out.length; i++) {
                if (unique.indexOf(out[i]) < 0) {
                    unique.push(out[i])
                }
            }
            return unique
        },

        /**
         * 组装 `R-04` 请求体（**不含 `metric_type`、不含 `unit`、不含 `user_id`**）。
         *
         * 与 R-01 的关键差异（后端为**局部更新**：未出现的字段保持原值）：
         *   对白名单内的字段**总是携带**（允许值为 `null`）—— 否则「清空备注 / 清空标签」不会生效。
         * 白名单外的字段（该指标的 forbidden）**一个都不出现**，避免 422「该指标不支持此字段」。
         */
        editPayload: function () {
            const form = this.form
            const payload = {}
            const fields = this.allowedFields()
            for (let i = 0; i < fields.length; i++) {
                const field = fields[i]
                const raw = form[field]
                const text = raw === null || raw === undefined ? '' : String(raw).trim()
                if (field === 'tags') {
                    payload.tags = form.tags && form.tags.length ? form.tags.slice() : null
                } else if (field === 'note') {
                    payload.note = text ? text : null
                } else if (field === 'value_1' || field === 'value_2' || field === 'value_3') {
                    payload[field] = text ? parseNumber(text) : null
                } else {
                    payload[field] = text ? text : null
                }
            }
            if (this.serverSoft) {
                // 软提示确认后原样重发 + 确认标记（与 R-01 同口径，S1-B §3.14）
                payload.acknowledge_warnings = true
            }
            return payload
        },

        /**
         * 编辑模式提交（R-04 `PATCH /records/{id}`）。
         *
         * 与新增模式的差异（如实登记）：
         *   · 请求体**不含 `metric_type`**（后端：携带即 422，即使值与原值相同）；
         *   · 后端 R-04 **未接入幂等键**（`patch_record` 无 idempotency 处理）⇒ 本支路不传 key，
         *     "防重复提交"由 `submitting` + 按钮 `disabled` 在客户端保证；
         *   · 成功后 → Toast「已保存」→ 返回 SC-09 详情（其 `onShow` 会重新拉取最新值）。
         * 软提示（`SOFT_WARNING`）与新增模式同口径：先出黄条，用户再次点击时携带 `acknowledge_warnings`。
         */
        submitEdit: function () {
            const self = this
            const payload = this.editPayload()
            this.submitting = true
            return updateRecord(this.recordId, payload).then(function (res) {
                self.submitting = false
                const code = res && res.code ? res.code : 'OK'

                if (code === 'SOFT_WARNING') {
                    // 服务端软提示（HTTP 200）：**本次未写入** ⇒ 展示固定文案（黄条），可继续保存
                    self.serverSoft = true
                    return
                }

                self.serverSoft = false
                self.savedOnce = true
                showToast('success', EDITED_TOAST_TEXT)
                self.backToDetail()
            }, function (err) {
                self.submitting = false

                if (err && err.isNetwork) {
                    // 弱网 / 超时：**结果未知** → 明确提示，**不自动重试**
                    showToast('error', '结果未知，请刷新后确认是否已保存')
                    return
                }

                if (err && (err.httpStatus === 404 || err.code === 'RESOURCE_NOT_FOUND')) {
                    // 记录已不存在（被删 / 越权）→ **统一按「记录不存在」**，不制造异常页面
                    self.recordNotFound = true
                    self.recordErrorText = EDIT_NOT_FOUND_TEXT
                    showToast('info', EDIT_NOT_FOUND_TEXT)
                    return
                }

                // 字段级 / 业务错误（422 等）：映射到字段，绝不静默
                self.applyServerErrors(err)
                if (self.blockText || self.hasFieldError()) {
                    return
                }
                showToast('error', errorText(err))
            })
        },

        /**
         * 编辑保存成功后的去向（S1-C ⑥/⑦：编辑模式保存成功 → 返回 SC-09 详情）。
         * ① 来源即 SC-09 → `navigateBack()`（SC-09 的 `onShow` 会重新拉取最新值）；
         * ② 来源为其他页（理论上不应发生）→ `redirectTo` SC-09，栈内不留"已保存的编辑页"。
         */
        backToDetail: function () {
            const pages = getCurrentPages()
            const prev = pages && pages.length > 1 ? pages[pages.length - 2] : null
            const prevRoute = prev && prev.route ? String(prev.route) : ''
            if (prevRoute.indexOf('record/detail') >= 0) {
                navigateBack()
                return
            }
            uni.redirectTo({
                url: ROUTES.RECORD_DETAIL + '?id=' + this.recordId + '&type=' + this.metricType
            })
        },

        /* ───────────── 提交（R-01） ───────────── */

        onSave: function () {
            this.submit(false)
        },

        onSaveContinue: function () {
            this.submit(true)
        },

        /**
         * @param {boolean} continueAfter 保存成功后是否**停留本页**继续记录（S1-C ⑦）
         */
        submit: function (continueAfter) {
            const self = this
            if (this.submitting || this.invalidType) {
                return
            }
            // 编辑模式：记录未就绪 / 载入失败 → 不可提交（与 `saveDisabled` 同口径）
            if (this.editMode && (this.recordLoading || !!this.recordErrorText)) {
                return
            }
            // 已尝试提交 → 一次性暴露全部字段错误（此后不再"静默"）
            this.attempted = true
            this.revalidate()

            if (this.blockText || this.hasFieldError()) {
                // 硬拦截：**不发请求**（红条 / 字段提示已展示；阻止保存）
                return
            }

            // 离线：**禁止写入**（绝不假装保存成功）→ 明确提示 + 保留内容 + 写草稿
            // （编辑模式同样禁止写入；但不写草稿 —— 见 `persistDraft`）
            if (this.offline) {
                this.persistDraft()
                showToast('error', offlineText('save'))
                return
            }

            // 编辑模式走 R-04 独立支路（请求体语义与 R-01 不同，不复用 `buildPayload`）
            if (this.editMode) {
                return this.submitEdit()
            }

            const payload = this.buildPayload()
            if (!this.submitKey) {
                this.submitKey = newIdempotencyKey()
            }

            this.submitting = true
            return createRecord(payload, this.submitKey).then(function (res) {
                self.submitting = false
                const code = res && res.code ? res.code : 'OK'

                if (code === 'SOFT_WARNING') {
                    // 服务端软提示（HTTP 200）：**本次未写入** ⇒ 展示固定文案（黄条），可继续保存；
                    // 用户再次点击保存时「原样重发 + acknowledge_warnings: true」（S1-B §3.14）。
                    self.serverSoft = true
                    return
                }

                // 保存成功
                self.serverSoft = false
                self.submitKey = null
                dropDraft(self.metricType)
                self.draftAvailable = false
                self.draftForm = null
                self.draftVisible = false
                self.applySavedRecord(res && res.data ? res.data.record : null)

                if (continueAfter) {
                    showToast('success', '已保存，可继续记录')
                    self.resetValuesForNext()
                    return
                }
                self.savedOnce = true
                showToast('success', '已保存')
                self.backToSource()
            }, function (err) {
                self.submitting = false

                if (err && err.isNetwork) {
                    // 弱网 / 超时：**结果未知** → 明确提示 + 保留输入，**不自动重试**（S1-C ⑭③）
                    self.persistDraft()
                    showToast('error', '结果未知，请刷新后确认是否已保存')
                    return
                }

                // 字段级 / 业务错误（422 / 409 等）：映射到字段，绝不静默
                self.applyServerErrors(err)
                if (self.blockText || self.hasFieldError()) {
                    return
                }
                self.persistDraft()
                showToast('error', errorText(err))
            })
        },

        /**
         * 组装 `R-01` 请求体（**不含 `unit`、不含 `user_id`**；空值一律不下发）。
         * ★ 本函数**只服务新增模式**；编辑模式的请求体语义不同（局部更新、无 `metric_type`），
         *   由 `editPayload()` 组装，两者不共用。
         */
        buildPayload: function () {
            const form = this.form
            const payload = { metric_type: this.metricType }
            const numeric = ['value_1', 'value_2', 'value_3']
            for (let i = 0; i < numeric.length; i++) {
                const field = numeric[i]
                const raw = form[field]
                const text = raw === null || raw === undefined ? '' : String(raw).trim()
                if (text) {
                    payload[field] = parseNumber(text)
                }
            }
            if (form.attr_1) {
                payload.attr_1 = form.attr_1
            }
            if (form.attr_2) {
                payload.attr_2 = form.attr_2
            }
            if (form.time_start) {
                payload.time_start = form.time_start
            }
            if (form.recorded_at) {
                payload.recorded_at = form.recorded_at
            }
            if (form.note && String(form.note).trim()) {
                payload.note = String(form.note).trim()
            }
            if (this.metricType === 'mood' && form.tags && form.tags.length) {
                payload.tags = form.tags.slice()
            }
            if (this.serverSoft) {
                // 软提示确认后原样重发 + 确认标记（S1-B §3.14）
                payload.acknowledge_warnings = true
            }
            return payload
        },

        /** 把服务端 `errors[]`（字段级明细）映射到表单提示（保留本地已有提示） */
        applyServerErrors: function (err) {
            this.revalidate()
            const map = {}
            for (const key in this.fieldErrors) {
                if (Object.prototype.hasOwnProperty.call(this.fieldErrors, key) && this.fieldErrors[key]) {
                    map[key] = this.fieldErrors[key]
                }
            }
            const fields = ['value_1', 'value_2', 'value_3', 'attr_1', 'attr_2',
                'recorded_at', 'time_start', 'note', 'tags', 'metric_type']
            fields.forEach(function (field) {
                const text = fieldErrorText(err, field)
                if (text) {
                    map[field] = text
                }
            })
            this.fieldErrors = map
        },

        /** 保存成功后：用服务端返回的记录刷新「上次值」（真实数据，不编造） */
        applySavedRecord: function (record) {
            if (!record) {
                return
            }
            this.lastRecord = record
        },

        /** 「保存并继续记录」→ 清空数值与标签，保留指标类型与时间基准；焦点回到输入框 */
        resetValuesForNext: function () {
            this.form.value_1 = ''
            this.form.value_2 = ''
            this.form.value_3 = ''
            this.form.tags = []
            this.form.note = ''
            // 清空校验痕迹：下一条记录从"干净状态"开始（不残留上一条的红字）
            this.touched = {}
            this.attempted = false
            this.focusValue = true
            this.revalidate()
        },

        /** 返回来源页（SC-06 / SC-07 的 `onShow` 会自动刷新数据） */
        backToSource: function () {
            const pages = getCurrentPages()
            if (pages && pages.length > 1) {
                navigateBack()
                return
            }
            reLaunch(ROUTES.RECORD)
        },

        /** 参数非法时的出口 → 记录中心 */
        backToRecord: function () {
            reLaunch(ROUTES.RECORD)
        },

        /* ───────────── 离开确认 ───────────── */

        /** 弹窗「继续填写」→ 留在本页 */
        onKeepEditing: function () {
            this.leaveVisible = false
        },

        /** 弹窗「放弃」→ 写草稿后返回（内容仍可在下次进入时恢复，不静默丢弃） */
        onDiscard: function () {
            this.leaveVisible = false
            this.persistDraft()
            this.savedOnce = true
            this.backToSource()
        }
    }
}
</script>

<style scoped lang="scss">
.add {
    min-height: 100vh;
    background-color: var(--s-page);
}

.add__body {
    /* A 类系统导航栏占位由平台负责，此处只留内容区节奏 */
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

/* 内容最大宽居中（DESIGN.md §10.4③） */
.add__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.add__block {
    margin-bottom: var(--card-gap);
}

/* ── 指标名 + 单位 ── */
.add__head {
    display: flex;
    flex-direction: row;
    align-items: baseline;
    margin-bottom: var(--sp-6);
}

.add__title {
    font-size: var(--fs-h1);
    line-height: $lh-h1;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.add__unit {
    margin-left: var(--sp-3);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── 字段标签 ── */
.add__label-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-bottom: var(--sp-3);
}

.add__label {
    display: block;
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.add__required {
    margin-left: var(--sp-1);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--c-danger);
    letter-spacing: 0;
}

/* ── 主数值区（大号输入） ── */
.add__value-box {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--tap-min);
    padding-left: var(--sp-5);
    padding-right: var(--sp-5);
    border-radius: var(--r-md);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-border);
    transition: border-color var(--d-fast) var(--ease-std);
}

.add__value-box--big {
    min-height: var(--row-h);
}

.add__value-box--error {
    border: 1rpx solid var(--c-danger);
}

.add__value-input {
    flex: 1;
    height: var(--tap-min);
    font-size: var(--fs-body);
    color: var(--t-1);
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
}

.add__value-input--big {
    height: var(--row-h);
    font-size: var(--fs-metric-xl);
    font-weight: $fw-semibold;
}

.add__value-unit {
    margin-left: var(--sp-3);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    letter-spacing: 0;
}

.add__field-error {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-danger);
    letter-spacing: 0;
}

.add__last {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-link);
    letter-spacing: 0;
    transition: opacity var(--d-fast) var(--ease-std);
}

.add__last--press {
    opacity: var(--press-opacity);
}

/* ── 派生值（睡眠时长；只显示数字，无分级标签） ── */
.add__derived {
    display: block;
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

/* ── 饮水快捷添加 ── */
.add__quick {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-top: var(--sp-1);
}

.add__quick-btn {
    flex: 1;
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-height: var(--tap-min);
    margin-right: var(--sp-3);
    border-radius: var(--r-sm);
    background-color: var(--s-brand-soft);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.add__quick-btn--last {
    margin-right: 0;
}

.add__quick-btn--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.add__quick-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--c-p-600);
    letter-spacing: 0;
}

/* ── 感受标签（多选） ── */
.add__tags {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    margin-top: var(--sp-1);
}

.add__tag {
    min-height: var(--tap-min);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    padding-left: var(--sp-5);
    padding-right: var(--sp-5);
    margin-right: var(--sp-3);
    margin-bottom: var(--sp-3);
    border-radius: var(--r-sm);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-border);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.add__tag--on {
    background-color: var(--s-brand-soft);
    border: 1rpx solid var(--c-p-600);
}

.add__tag--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.add__tag-text {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.add__tag-text--on {
    color: var(--c-p-600);
    font-weight: $fw-medium;
}

/* ── 底部按钮（文档流内布局，**不用 fixed** ⇒ 任何屏宽下都不会遮挡内容） ── */
.add__foot {
    margin-top: var(--sp-6);
}

.add__foot-item {
    margin-bottom: var(--sp-3);
}
</style>
