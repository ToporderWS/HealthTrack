import { createPinia } from 'pinia'

// S1-D 冻结：前端状态管理 = Pinia 2.x。
// S2 第一批只提供 Pinia 实例；业务 store（用户 / 缓存 / 网络）在后续批次实现，
// 本阶段不注册任何业务 store。
const store = createPinia()

export default store
