<template>
    <!--
      C-12 AppModal（G6 二次确认 / G7 强确认危险弹窗）
      规格：mode = info / confirm / danger（红色 + 后果清单 + 文本输入 + 密码输入）；
            底部抽屉（顶两角 var(--r-xl)）；**danger 不可点遮罩关闭**。
      八态：default（显示中）/ pressed（按钮按下）/ disabled（未勾选 / 未填必填项） / error（校验失败）
            / loading(N/A — 提交中的 loading 由内部 AppButton 承载) / success(N/A) / empty(N/A)
            / offline（由调用方在提交前拦截）

      ★ 如实登记（状态 N/A 原因）：
        mode="danger" 的「文本输入 + 密码输入」属 **SC-22 数据删除 / 注销账号（S3-8）** 场景，
        本批（S3-1）不使用 —— 因此本批只实现 danger 的**视觉与遮罩行为**（红色主按钮 + 不可点遮罩关闭），
        **不实现** 文本输入 / 密码输入子表单（避免为目标批次预造无用 UI）。S3-8 落地时再按同一契约补齐。
    -->
    <view v-if="show" class="modal">
        <view class="modal__mask" @tap="handleMask"></view>
        <view class="modal__panel">
            <view v-if="title" class="modal__head">
                <text class="modal__title">{{ title }}</text>
            </view>

            <view class="modal__body">
                <slot>
                    <text v-if="content" class="modal__text">{{ content }}</text>
                </slot>
            </view>

            <view class="modal__foot">
                <view v-if="showCancel" class="modal__btn modal__btn--cancel" hover-class="modal__btn--press" @tap="handleCancel">
                    <text class="modal__btn-text modal__btn-text--cancel">{{ cancelText }}</text>
                </view>
                <view
                    class="modal__btn modal__btn--confirm"
                    :class="{ 'modal__btn--danger': mode === 'danger', 'modal__btn--disabled': confirmDisabled }"
                    :hover-class="confirmDisabled ? 'none' : 'modal__btn--press'"
                    @tap="handleConfirm"
                >
                    <text class="modal__btn-text modal__btn-text--confirm">{{ confirmText }}</text>
                </view>
            </view>
            <view class="modal__safe"></view>
        </view>
    </view>
</template>

<script>
export default {
    name: 'AppModal',
    props: {
        show: { type: Boolean, default: false },
        mode: { type: String, default: 'info' },
        title: { type: String, default: '' },
        content: { type: String, default: '' },
        confirmText: { type: String, default: '确定' },
        cancelText: { type: String, default: '取消' },
        showCancel: { type: Boolean, default: true },
        confirmDisabled: { type: Boolean, default: false },
        /** danger 模式忽略该值（强制不可点遮罩关闭） */
        closeOnMask: { type: Boolean, default: true }
    },
    emits: ['update:show', 'confirm', 'cancel'],
    methods: {
        handleMask: function () {
            if (this.mode === 'danger' || !this.closeOnMask) {
                return
            }
            this.handleCancel()
        },
        handleCancel: function () {
            this.$emit('update:show', false)
            this.$emit('cancel')
        },
        handleConfirm: function () {
            if (this.confirmDisabled) {
                return
            }
            this.$emit('confirm')
        }
    }
}
</script>

<style scoped lang="scss">
.modal {
    position: fixed;
    left: 0;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 100;
}

.modal__mask {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    bottom: 0;
    background-color: var(--s-overlay);
}

.modal__panel {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    background-color: var(--s-card);
    border-radius: var(--r-xl) var(--r-xl) 0 0;
    padding: var(--sp-7) var(--card-pad) 0 var(--card-pad);
    animation: modal-up var(--d-slow) var(--ease-out);
}

.modal__head {
    display: flex;
    flex-direction: row;
    justify-content: center;
    margin-bottom: var(--sp-5);
}

.modal__title {
    font-size: var(--fs-h2);
    line-height: $lh-h2;
    font-weight: $fw-semibold;
    color: var(--t-1);
    text-align: center;
    letter-spacing: 0;
}

.modal__body {
    max-height: 720rpx;
}

.modal__text {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-2);
    letter-spacing: 0;
}

.modal__foot {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-top: var(--sp-8);
    padding-bottom: var(--sp-5);
}

.modal__btn {
    flex: 1;
    height: 96rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--r-md);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.modal__btn--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.modal__btn--cancel {
    background-color: var(--s-sunken);
    margin-right: var(--sp-5);
}

.modal__btn--confirm {
    background-color: var(--c-p-600);
}

.modal__btn--danger {
    background-color: var(--c-danger);
}

.modal__btn--disabled {
    background-color: var(--s-sunken);
}

.modal__btn-text {
    font-size: var(--fs-btn-l);
    line-height: $lh-btn-l;
    font-weight: $fw-semibold;
    letter-spacing: 0;
}

.modal__btn-text--cancel {
    color: var(--t-2);
}

.modal__btn-text--confirm {
    color: var(--t-inverse);
}

.modal__btn--disabled .modal__btn-text--confirm {
    color: var(--t-4);
}

.modal__safe {
    height: var(--safe-b);
}

@keyframes modal-up {
    from {
        transform: translateY(100%);
    }
    to {
        transform: translateY(0);
    }
}
</style>
