import { createSSRApp } from 'vue'
import App from './App.vue'
import store from './store'

/**
 * ── 运行期缺陷兜底（H5 本机运行环境；2026-09-17 定位并取证）──
 *
 * 【现象】H5 下，「组件模板里写在 <view> 内的子组件」只要发生一次 props 变化
 *   （如输入框获焦使绑定 class 变化），即抛
 *   TypeError: Cannot assign to read only property '_' of object
 *   -> 该组件本次更新被整体中止（界面表现为该元素不重绘）；
 *   -> 之后卸载该页面时继续抛 Cannot read properties of null
 *      (reading 'type' / 'subTree' / 'parentNode')；
 *   -> 卸载失败使整次路由切换中止 => 表现为「点击跳转无反应」
 *      （SC-02 轮播/协议弹窗、SC-04 去登录 均由此引起）。
 *
 * 【根因】HBuilderX 内置 @dcloudio/uni-h5-vue（3.4.21 分支）+ @vue/shared：
 *   def() 用 Object.defineProperty 定义**不可写**属性；initSlots() 里
 *   instance.slots = toRaw(children) 与编译期 slot 对象是**同一个对象**，
 *   紧接 def(children, '_', type) 把内部标记 '_' 定为不可写；而 updateSlots()
 *   在 optimized === false 分支执行 extend(slots, children)（Object.assign
 *   自赋值）时会写这个只读键 => 抛 TypeError（该帧全部落在运行时内部，
 *   工程侧无一帧参与）。
 *   官方 Vue 3.5 已修复：assignSlots() 跳过 '_' 等内部键，并把该标记置为可写。
 *
 * 【兜底】只拦截「内部标记 '_'、值为 1 或 2（STABLE/DYNAMIC）、不可枚举、
 *   可配置、原本不可写」这一种 defineProperty 调用，把 writable 置为 true，
 *   与官方修复语义一致：extend 自赋值不再抛错（写入前后取值相同），
 *   后续仍按原逻辑 delete slots._。范围仅此一处，不改页面 / 组件 / DESIGN 契约。
 *   内置运行时升级到含官方修复的版本后，本段可整体删除。
 */
;(function patchUniH5VueSlotMarker() {
    const rawDefineProperty = Object.defineProperty
    if (!rawDefineProperty || rawDefineProperty.__kjSlotMarkerPatched) {
        return
    }
    function definePropertyPatched(target, key, descriptor) {
        if (
            key === '_' &&
            descriptor &&
            (descriptor.value === 1 || descriptor.value === 2) &&
            descriptor.enumerable === false &&
            descriptor.configurable === true &&
            !descriptor.writable
        ) {
            descriptor.writable = true
        }
        return rawDefineProperty(target, key, descriptor)
    }
    definePropertyPatched.__kjSlotMarkerPatched = true
    Object.defineProperty = definePropertyPatched
})()

// S2 第一批：工程骨架入口。
// 应用以 <script setup> 之外的函数式工厂创建（uni-app Vue3 约定：createSSRApp）。
export function createApp() {
    const app = createSSRApp(App)
    app.use(store)
    return {
        app
    }
}
